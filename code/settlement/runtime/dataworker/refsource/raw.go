// Package refsource retrieves reference observations for the experimental
// data comparison from public price-quote endpoints. Every retrieval produces a
// raw replay object that keeps the exact request and response bytes, the URL,
// the local capture time and the TLS session details. Observations are always
// derived from a raw object, both when capturing live and when replaying.
package refsource

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Format identifies version 1 of the raw replay object encoding.
const Format = "fairbind/refsource-raw/v1"

// MaxResponseBytes bounds the recorded response (status line, headers and body).
const MaxResponseBytes = 1 << 20

// RawObject is the evidence unit. ResponseRaw holds the exact bytes read from
// the TLS stream, including the status line, headers and transfer framing.
// ResponseHead is a readable copy of the status line and header block; Verify
// requires it to equal the prefix of ResponseRaw.
type RawObject struct {
	Format         string     `json:"format"`
	SourceID       string     `json:"source_id"`
	Method         string     `json:"method"`
	URL            string     `json:"url"`
	RequestRaw     []byte     `json:"request_raw"`
	StartedAtMs    int64      `json:"started_at_unix_ms"`
	FinishedAtMs   int64      `json:"finished_at_unix_ms"`
	ResponseRaw    []byte     `json:"response_raw"`
	ResponseSHA256 string     `json:"response_sha256"`
	ResponseHead   string     `json:"response_head"`
	TLS            TLSRecord  `json:"tls"`
	Capture        CaptureTag `json:"capture"`
}

// TLSRecord keeps what the client can observe about the TLS session. It does not
// make the response transferable proof: TLS does not sign application data, so a
// replay is only as trustworthy as the party that captured it.
type TLSRecord struct {
	Version           string   `json:"version"`
	CipherSuite       string   `json:"cipher_suite"`
	ServerName        string   `json:"server_name"`
	NegotiatedALPN    string   `json:"alpn"`
	DidResume         bool     `json:"did_resume"`
	PeerCertificates  [][]byte `json:"peer_certificates_der"`
	OCSPResponse      []byte   `json:"ocsp_response,omitempty"`
	SCTs              [][]byte `json:"signed_certificate_timestamps,omitempty"`
	RemoteAddr        string   `json:"remote_addr"`
	VerifiedChainRoot string   `json:"verified_chain_root_sha256"`
}

// CaptureTag records how the object was produced. Synthetic objects are built
// by hand for tests and carry no TLS session; Verify rejects them by default.
type CaptureTag struct {
	Tool      string `json:"tool"`
	Synthetic bool   `json:"synthetic"`
	Proxy     string `json:"proxy,omitempty"`
	Note      string `json:"note,omitempty"`
}

// VerifyOptions controls replay verification.
type VerifyOptions struct {
	// Roots verifies the recorded chain. Nil uses the system pool.
	Roots *x509.CertPool
	// AllowSynthetic accepts hand-built test objects without a TLS chain.
	AllowSynthetic bool
	// MaxDateDrift bounds |Date header - local capture window|. Zero means 5 minutes.
	MaxDateDrift time.Duration
}

// Response is a parsed, verified raw object.
type Response struct {
	Object *RawObject
	Status int
	Header http.Header
	Body   []byte
	// Date is the server Date header, the time used as the observation time.
	Date time.Time
}

// SHA256Hex returns the lowercase hex SHA-256 of b.
func SHA256Hex(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

// ObjectID is the SHA-256 of the object's JSON encoding. Go encodes struct
// fields in declaration order, so the encoding is stable for a given object.
func (o *RawObject) ObjectID() (string, error) {
	b, e := json.Marshal(o)
	if e != nil {
		return "", e
	}
	return SHA256Hex(b), nil
}

// Load reads one raw object file, rejecting unknown members and trailing data.
func Load(path string) (*RawObject, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return nil, e
	}
	return Decode(b)
}

// Decode parses one raw object encoding.
func Decode(b []byte) (*RawObject, error) {
	if len(b) > 4*MaxResponseBytes {
		return nil, errors.New("raw object too large")
	}
	if e := checkNoDuplicates(b); e != nil {
		return nil, e
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	var o RawObject
	if e := d.Decode(&o); e != nil {
		return nil, e
	}
	if d.More() {
		return nil, errors.New("trailing data after raw object")
	}
	return &o, nil
}

// Verify checks the object's internal consistency and, for captured objects,
// the recorded certificate chain against the configured roots at capture time.
// It then parses the HTTP response from the raw bytes.
func Verify(o *RawObject, opt VerifyOptions) (*Response, error) {
	if o == nil || o.Format != Format {
		return nil, errors.New("unsupported raw object format")
	}
	if o.Method != http.MethodGet || o.SourceID == "" {
		return nil, errors.New("unsupported request")
	}
	u, e := url.Parse(o.URL)
	if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" {
		return nil, errors.New("reference URL must be plain https")
	}
	if len(o.ResponseRaw) == 0 || len(o.ResponseRaw) > MaxResponseBytes {
		return nil, errors.New("response size")
	}
	if SHA256Hex(o.ResponseRaw) != o.ResponseSHA256 {
		return nil, errors.New("response hash mismatch")
	}
	if !bytes.HasPrefix(o.ResponseRaw, []byte(o.ResponseHead)) || !strings.HasSuffix(o.ResponseHead, "\r\n\r\n") {
		return nil, errors.New("response head mismatch")
	}
	if o.StartedAtMs <= 0 || o.FinishedAtMs < o.StartedAtMs {
		return nil, errors.New("capture window")
	}
	if e := checkRequest(o, u); e != nil {
		return nil, e
	}
	if o.Capture.Synthetic {
		if !opt.AllowSynthetic {
			return nil, errors.New("synthetic raw object")
		}
		if len(o.TLS.PeerCertificates) != 0 {
			return nil, errors.New("synthetic object carries a certificate chain")
		}
	} else if e := verifyChain(o, u.Hostname(), opt.Roots); e != nil {
		return nil, e
	}
	req, _ := http.NewRequest(o.Method, o.URL, nil)
	br := bufio.NewReader(bytes.NewReader(o.ResponseRaw))
	resp, e := http.ReadResponse(br, req)
	if e != nil {
		return nil, fmt.Errorf("response framing: %w", e)
	}
	body, e := io.ReadAll(io.LimitReader(resp.Body, MaxResponseBytes+1))
	resp.Body.Close()
	if e != nil || len(body) > MaxResponseBytes {
		return nil, errors.New("response body")
	}
	if _, e := br.Peek(1); e != io.EOF {
		return nil, errors.New("trailing bytes after response")
	}
	if ce := resp.Header.Get("Content-Encoding"); ce != "" && !strings.EqualFold(ce, "identity") {
		return nil, errors.New("unsupported content encoding")
	}
	date, e := http.ParseTime(resp.Header.Get("Date"))
	if e != nil {
		return nil, errors.New("missing or malformed Date header")
	}
	drift := opt.MaxDateDrift
	if drift == 0 {
		drift = 5 * time.Minute
	}
	lo := time.UnixMilli(o.StartedAtMs).Add(-drift - time.Second)
	hi := time.UnixMilli(o.FinishedAtMs).Add(drift)
	if date.Before(lo) || date.After(hi) {
		return nil, errors.New("Date header outside capture window")
	}
	return &Response{Object: o, Status: resp.StatusCode, Header: resp.Header, Body: body, Date: date}, nil
}

func checkRequest(o *RawObject, u *url.URL) error {
	r, e := http.ReadRequest(bufio.NewReader(bytes.NewReader(o.RequestRaw)))
	if e != nil {
		return errors.New("request framing")
	}
	if r.Method != o.Method || r.Host != u.Host || r.URL.RequestURI() != u.RequestURI() {
		return errors.New("recorded request does not match URL")
	}
	return nil
}

func verifyChain(o *RawObject, host string, roots *x509.CertPool) error {
	if len(o.TLS.PeerCertificates) == 0 {
		return errors.New("no certificate chain recorded")
	}
	if o.TLS.ServerName != host {
		return errors.New("TLS server name does not match URL host")
	}
	switch o.TLS.Version {
	case "TLS1.2", "TLS1.3":
	default:
		return errors.New("unsupported TLS version")
	}
	certs := make([]*x509.Certificate, len(o.TLS.PeerCertificates))
	for i, der := range o.TLS.PeerCertificates {
		c, e := x509.ParseCertificate(der)
		if e != nil {
			return errors.New("recorded certificate")
		}
		certs[i] = c
	}
	inter := x509.NewCertPool()
	for _, c := range certs[1:] {
		inter.AddCert(c)
	}
	chains, e := certs[0].Verify(x509.VerifyOptions{DNSName: host, Roots: roots, Intermediates: inter, CurrentTime: time.UnixMilli(o.StartedAtMs)})
	if e != nil {
		return fmt.Errorf("recorded chain: %w", e)
	}
	for _, ch := range chains {
		if SHA256Hex(ch[len(ch)-1].Raw) == o.TLS.VerifiedChainRoot {
			return nil
		}
	}
	return errors.New("recorded chain root differs from capture")
}

// checkNoDuplicates walks a JSON text and rejects duplicate object members and
// trailing values. encoding/json alone keeps the last duplicate silently.
func checkNoDuplicates(b []byte) error {
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var walk func() error
	walk = func() error {
		t, e := d.Token()
		if e != nil {
			return e
		}
		switch t {
		case json.Delim('{'):
			seen := map[string]bool{}
			for d.More() {
				k, e := d.Token()
				if e != nil {
					return e
				}
				key := k.(string)
				if seen[key] {
					return fmt.Errorf("duplicate JSON member %q", key)
				}
				seen[key] = true
				if e := walk(); e != nil {
					return e
				}
			}
			_, e = d.Token()
			return e
		case json.Delim('['):
			for d.More() {
				if e := walk(); e != nil {
					return e
				}
			}
			_, e = d.Token()
			return e
		}
		return nil
	}
	if e := walk(); e != nil {
		return e
	}
	if _, e := d.Token(); e != io.EOF {
		return errors.New("trailing JSON data")
	}
	return nil
}
