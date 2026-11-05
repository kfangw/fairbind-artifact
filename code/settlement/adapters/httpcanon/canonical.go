// Package httpcanon implements the raw HTTP boundary in canonicalization-v1.
// Callers must supply the undecoded request target and pre-content-decoding body.
package httpcanon

import (
	"fmt"
	"example.org/fairbind/protocol"
	"sort"
	"strings"
)

var ID = protocol.Keccak256([]byte("fairbind/http-canon/v1"))

type Header struct{ Name, Value string }
type Request struct {
	Method, Path, Query string
	Headers             []Header
	Body                []byte
}
type Canonical struct {
	Method, Path, Query, Headers string
	Body                         []byte
}

func (c Canonical) Hash() protocol.Bytes32 {
	parts := []protocol.Bytes32{ID, protocol.Keccak256([]byte(c.Method)), protocol.Keccak256([]byte(c.Path)), protocol.Keccak256([]byte(c.Query)), protocol.Keccak256([]byte(c.Headers)), protocol.Keccak256(c.Body)}
	var encoded []byte
	for _, p := range parts {
		encoded = append(encoded, p[:]...)
	}
	return protocol.Keccak256(encoded)
}
func percent(s string) (string, error) {
	var out strings.Builder
	const hex = "0123456789ABCDEF"
	value := func(c byte) int {
		if c >= '0' && c <= '9' {
			return int(c - '0')
		}
		if c >= 'a' && c <= 'f' {
			return int(c - 'a' + 10)
		}
		if c >= 'A' && c <= 'F' {
			return int(c - 'A' + 10)
		}
		return -1
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c < 32 || c > 126 {
			return "", fmt.Errorf("raw_non_ascii")
		}
		if c != '%' {
			out.WriteByte(c)
			continue
		}
		if i+2 >= len(s) || value(s[i+1]) < 0 || value(s[i+2]) < 0 {
			return "", fmt.Errorf("invalid_percent_encoding")
		}
		c = byte(value(s[i+1])*16 + value(s[i+2]))
		i += 2
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("-._~", rune(c)) {
			out.WriteByte(c)
		} else {
			out.WriteByte('%')
			out.WriteByte(hex[c>>4])
			out.WriteByte(hex[c&15])
		}
	}
	return out.String(), nil
}
func dots(in string) string {
	out := ""
	pop := func() {
		if i := strings.LastIndexByte(out, '/'); i >= 0 {
			out = out[:i]
		} else {
			out = ""
		}
	}
	for in != "" {
		switch {
		case strings.HasPrefix(in, "../"):
			in = in[3:]
		case strings.HasPrefix(in, "./"):
			in = in[2:]
		case strings.HasPrefix(in, "/./"):
			in = in[2:]
		case in == "/.":
			in = "/"
		case strings.HasPrefix(in, "/../"):
			in = in[3:]
			pop()
		case in == "/..":
			in = "/"
			pop()
		case in == "." || in == "..":
			in = ""
		default:
			start := 0
			if in[0] == '/' {
				start = 1
			}
			i := strings.IndexByte(in[start:], '/')
			if i < 0 {
				out += in
				in = ""
			} else {
				i += start
				out += in[:i]
				in = in[i:]
			}
		}
	}
	return out
}
func token(s string) bool {
	if s == "" {
		return false
	}
	for i := range s {
		c := s[i]
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || strings.ContainsRune("!#$%&'*+-.^_`|~", rune(c))) {
			return false
		}
	}
	return true
}

// Normalize uses an explicit operator allowlist for comma-joinable headers;
// an unknown field's grammar is never inferred from its name.
func Normalize(r Request, names []string, joinable map[string]bool, maxBytes int) (Canonical, error) {
	bad := func(reason string) (Canonical, error) { return Canonical{}, fmt.Errorf("%s", reason) }
	total := len(r.Method) + len(r.Path) + len(r.Query) + len(r.Body)
	for _, h := range r.Headers {
		total += len(h.Name) + len(h.Value)
	}
	if maxBytes <= 0 || total > maxBytes || len(names) > 128 || len(r.Headers) > 1024 {
		return bad("request_limit")
	}
	if r.Method == "" {
		return bad("invalid_method")
	}
	for i := range r.Method {
		if r.Method[i] < 33 || r.Method[i] > 126 {
			return bad("invalid_method")
		}
	}
	if r.Path == "" {
		r.Path = "/"
	}
	if r.Path[0] != '/' {
		return bad("path_not_absolute")
	}
	path, err := percent(r.Path)
	if err != nil {
		return Canonical{}, err
	}
	var pairs [][2]string
	if r.Query != "" {
		for _, field := range strings.Split(r.Query, "&") {
			kv := strings.SplitN(field, "=", 2)
			v := ""
			if len(kv) == 2 {
				v = kv[1]
			}
			k, e := percent(kv[0])
			if e != nil {
				return Canonical{}, e
			}
			v, e = percent(v)
			if e != nil {
				return Canonical{}, e
			}
			pairs = append(pairs, [2]string{k, v})
		}
	}
	sort.SliceStable(pairs, func(i, j int) bool {
		if pairs[i][0] == pairs[j][0] {
			return pairs[i][1] < pairs[j][1]
		}
		return pairs[i][0] < pairs[j][0]
	})
	q := []string{}
	for _, p := range pairs {
		q = append(q, p[0]+"="+p[1])
	}
	forbidden := map[string]bool{}
	for _, n := range strings.Fields("payment-required payment-signature payment-response x-fairbind-key x-fairbind-payer x-fairbind-receipt connection keep-alive proxy-authenticate proxy-authorization te trailer transfer-encoding upgrade content-length set-cookie") {
		forbidden[n] = true
	}
	for _, h := range r.Headers {
		if strings.EqualFold(h.Name, "connection") {
			for _, n := range strings.Split(h.Value, ",") {
				forbidden[strings.ToLower(strings.TrimSpace(n))] = true
			}
		}
	}
	var block strings.Builder
	selected := map[string]bool{}
	for i, n := range names {
		if !token(n) || i > 0 && names[i-1] >= n || forbidden[n] || !joinable[n] {
			return bad("invalid_profile_header")
		}
		selected[n] = true
		var values []string
		for _, h := range r.Headers {
			if !strings.EqualFold(h.Name, n) {
				continue
			}
			for j := range h.Value {
				c := h.Value[j]
				if c != '\t' && (c < 32 || c > 126) {
					return bad("canonical_header_invalid")
				}
			}
			values = append(values, strings.Join(strings.Fields(h.Value), " "))
		}
		if len(values) == 0 {
			return bad("canonical_header_missing")
		}
		block.WriteString(n + ":" + strings.Join(values, ",") + "\n")
	}
	for _, h := range r.Headers {
		if strings.EqualFold(h.Name, "content-encoding") && !selected["content-encoding"] {
			return bad("unbound_content_encoding")
		}
	}
	c := Canonical{strings.ToUpper(r.Method), dots(path), strings.Join(q, "&"), block.String(), append([]byte(nil), r.Body...)}
	if len(c.Method)+len(c.Path)+len(c.Query)+len(c.Headers)+len(c.Body) > maxBytes {
		return bad("normalized_request_limit")
	}
	return c, nil
}
func (c Canonical) CheckRoute(actual string) error {
	if actual != c.Path {
		return fmt.Errorf("route_mismatch")
	}
	return nil
}
