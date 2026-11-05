package refsource

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Capturer performs one HTTPS GET per call over a fresh TLS connection and
// records the exact bytes exchanged. It speaks HTTP/1.1 directly instead of
// using net/http's client so that the recorded response is the byte stream the
// server sent, not a re-serialization.
type Capturer struct {
	// Roots validates the server chain. Nil uses the system pool.
	Roots *x509.CertPool
	// Timeout bounds one capture. Zero means 15 seconds.
	Timeout time.Duration
	// Proxy, when set, is an http:// proxy used through CONNECT. The TLS session
	// is still end to end with the origin; a proxy that intercepts TLS fails
	// chain validation unless its CA was added to Roots, and the recorded chain
	// shows it.
	Proxy *url.URL
	// DialAddr overrides the TCP address (host:port) for tests. The TLS server
	// name and Host header still come from the URL.
	DialAddr string
	// UserAgent is sent with each request. Some exchanges reject requests without one.
	UserAgent string
	// Now is the capture clock. Nil uses time.Now.
	Now func() time.Time
}

// ProxyFromEnvironment returns the HTTPS_PROXY (or https_proxy) setting, if any.
func ProxyFromEnvironment() (*url.URL, error) {
	v := os.Getenv("HTTPS_PROXY")
	if v == "" {
		v = os.Getenv("https_proxy")
	}
	if v == "" {
		return nil, nil
	}
	u, e := url.Parse(v)
	if e != nil || u.Scheme != "http" || u.Host == "" {
		return nil, fmt.Errorf("unsupported proxy %q: only http:// CONNECT proxies are supported", v)
	}
	return u, nil
}

// Capture failure stages. StageConnect covers name resolution, TCP connection,
// the proxy CONNECT exchange and the TLS handshake: no HTTP response from the
// origin exists. StageExchange is a failure after the handshake and before a
// complete status line and header block. StageResponse is a failure after the
// response head was read (body, framing or size).
const (
	StageConnect  = "connect"
	StageExchange = "exchange"
	StageResponse = "response"
)

// CaptureError is returned by Capture when no raw object could be produced.
// Stage tells whether any HTTP response bytes were received.
type CaptureError struct {
	Stage string
	Err   error
}

func (e *CaptureError) Error() string { return e.Err.Error() }
func (e *CaptureError) Unwrap() error { return e.Err }

func stageErr(stage string, e error) error { return &CaptureError{Stage: stage, Err: e} }

// Capture fetches rawURL and returns the raw replay object. A non-200 status is
// still returned as an object; the caller parses and rejects it so that failed
// responses are retained as evidence too.
func (c Capturer) Capture(ctx context.Context, sourceID, rawURL string) (*RawObject, error) {
	u, e := url.Parse(rawURL)
	if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" {
		return nil, errors.New("reference URL must be plain https")
	}
	now := c.Now
	if now == nil {
		now = time.Now
	}
	timeout := c.Timeout
	if timeout == 0 {
		timeout = 15 * time.Second
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	host := u.Hostname()
	port := u.Port()
	if port == "" {
		port = "443"
	}
	target := net.JoinHostPort(host, port)
	ua := c.UserAgent
	if ua == "" {
		ua = "fairbind-refcapture/1"
	}
	var req bytes.Buffer
	fmt.Fprintf(&req, "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n", u.RequestURI(), u.Host, ua)

	started := now()
	conn, proxyName, e := c.dial(ctx, target)
	if e != nil {
		return nil, stageErr(StageConnect, e)
	}
	defer conn.Close()
	if d, ok := ctx.Deadline(); ok {
		conn.SetDeadline(d)
	}
	tc := tls.Client(conn, &tls.Config{ServerName: host, RootCAs: c.Roots, MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}})
	if e := tc.HandshakeContext(ctx); e != nil {
		return nil, stageErr(StageConnect, fmt.Errorf("TLS handshake: %w", e))
	}
	st := tc.ConnectionState()
	if st.NegotiatedProtocol != "" && st.NegotiatedProtocol != "http/1.1" {
		return nil, stageErr(StageExchange, errors.New("server did not accept HTTP/1.1"))
	}
	if _, e := tc.Write(req.Bytes()); e != nil {
		return nil, stageErr(StageExchange, e)
	}
	var raw bytes.Buffer
	lr := &io.LimitedReader{R: tc, N: MaxResponseBytes + 1}
	br := bufio.NewReader(io.TeeReader(lr, &raw))
	hreq, _ := http.NewRequest(http.MethodGet, rawURL, nil)
	resp, e := http.ReadResponse(br, hreq)
	if e != nil {
		return nil, stageErr(StageExchange, fmt.Errorf("response framing: %w", e))
	}
	_, e = io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if e != nil {
		return nil, stageErr(StageResponse, fmt.Errorf("response body: %w", e))
	}
	if raw.Len() > MaxResponseBytes {
		return nil, stageErr(StageResponse, errors.New("response size"))
	}
	finished := now()
	b := raw.Bytes()
	head := b
	if i := bytes.Index(b, []byte("\r\n\r\n")); i >= 0 {
		head = b[:i+4]
	}
	rec := TLSRecord{
		Version:        tlsVersion(st.Version),
		CipherSuite:    tls.CipherSuiteName(st.CipherSuite),
		ServerName:     st.ServerName,
		NegotiatedALPN: st.NegotiatedProtocol,
		DidResume:      st.DidResume,
		OCSPResponse:   st.OCSPResponse,
		SCTs:           st.SignedCertificateTimestamps,
		RemoteAddr:     conn.RemoteAddr().String(),
	}
	for _, cert := range st.PeerCertificates {
		rec.PeerCertificates = append(rec.PeerCertificates, cert.Raw)
	}
	if len(st.VerifiedChains) > 0 {
		ch := st.VerifiedChains[0]
		rec.VerifiedChainRoot = SHA256Hex(ch[len(ch)-1].Raw)
	}
	return &RawObject{
		Format:         Format,
		SourceID:       sourceID,
		Method:         http.MethodGet,
		URL:            rawURL,
		RequestRaw:     req.Bytes(),
		StartedAtMs:    started.UnixMilli(),
		FinishedAtMs:   finished.UnixMilli(),
		ResponseRaw:    append([]byte(nil), b...),
		ResponseSHA256: SHA256Hex(b),
		ResponseHead:   string(head),
		TLS:            rec,
		Capture:        CaptureTag{Tool: "refsource.Capturer/1", Proxy: proxyName},
	}, nil
}

func (c Capturer) dial(ctx context.Context, target string) (net.Conn, string, error) {
	var d net.Dialer
	if c.DialAddr != "" {
		conn, e := d.DialContext(ctx, "tcp", c.DialAddr)
		return conn, "", e
	}
	if c.Proxy == nil {
		conn, e := d.DialContext(ctx, "tcp", target)
		return conn, "", e
	}
	paddr := c.Proxy.Host
	if c.Proxy.Port() == "" {
		paddr = net.JoinHostPort(c.Proxy.Hostname(), "80")
	}
	conn, e := d.DialContext(ctx, "tcp", paddr)
	if e != nil {
		return nil, "", e
	}
	if dl, ok := ctx.Deadline(); ok {
		conn.SetDeadline(dl)
	}
	fmt.Fprintf(conn, "CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n", target, target)
	br := bufio.NewReader(conn)
	resp, e := http.ReadResponse(br, &http.Request{Method: http.MethodConnect})
	if e != nil || resp.StatusCode != http.StatusOK || br.Buffered() != 0 {
		conn.Close()
		return nil, "", errors.New("proxy CONNECT failed")
	}
	conn.SetDeadline(time.Time{})
	return conn, c.Proxy.Host, nil
}

func tlsVersion(v uint16) string {
	switch v {
	case tls.VersionTLS12:
		return "TLS1.2"
	case tls.VersionTLS13:
		return "TLS1.3"
	}
	return strings.ToUpper(fmt.Sprintf("0x%04x", v))
}
