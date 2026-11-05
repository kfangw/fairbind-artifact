package httpcanon

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

func TestNormativeVectors(t *testing.T) {
	raw, e := os.ReadFile("../../test-vectors/canonicalization-v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var doc struct {
		Positive []struct {
			Name  string
			Input struct {
				Method, Path, Query, BodyHex string
				CanonicalHeaders             []string
				Headers                      [][2]string
			}
			Normalized struct{ Method, Path, Query, HeaderBlockHex string }
			Hashes     struct{ RequestHash string }
		}
	}
	if e = json.Unmarshal(raw, &doc); e != nil {
		t.Fatal(e)
	}
	for _, v := range doc.Positive {
		t.Run(v.Name, func(t *testing.T) {
			body, _ := hex.DecodeString(v.Input.BodyHex[2:])
			r := Request{Method: v.Input.Method, Path: v.Input.Path, Query: v.Input.Query, Body: body}
			allow := map[string]bool{}
			for _, n := range v.Input.CanonicalHeaders {
				allow[n] = true
			}
			for _, h := range v.Input.Headers {
				r.Headers = append(r.Headers, Header{h[0], h[1]})
			}
			c, e := Normalize(r, v.Input.CanonicalHeaders, allow, 65536)
			if e != nil {
				t.Fatal(e)
			}
			if c.Method != v.Normalized.Method || c.Path != v.Normalized.Path || c.Query != v.Normalized.Query || "0x"+hex.EncodeToString([]byte(c.Headers)) != v.Normalized.HeaderBlockHex || fmt.Sprintf("0x%x", c.Hash()) != v.Hashes.RequestHash {
				t.Fatalf("vector mismatch: %+v", c)
			}
		})
	}
}
func TestRejectInvalidAndUnboundInputs(t *testing.T) {
	for _, path := range []string{"/v1/%zz", "v1/data", "/précis"} {
		if _, e := Normalize(Request{Method: "GET", Path: path}, nil, nil, 65536); e == nil {
			t.Fatal(path)
		}
	}
	cases := []struct {
		names   []string
		headers []Header
		allow   map[string]bool
	}{{[]string{"accept", "x-model"}, []Header{{"Accept", "application/json"}}, map[string]bool{"accept": true, "x-model": true}}, {[]string{"x-model"}, []Header{{"x-model", "a\r\n b"}}, map[string]bool{"x-model": true}}, {[]string{"x-model"}, []Header{{"x-model", "a"}, {"Connection", "x-model"}}, map[string]bool{"x-model": true}}, {nil, []Header{{"Content-Encoding", "gzip"}}, nil}, {[]string{"payment-signature"}, []Header{{"Payment-Signature", "value"}}, map[string]bool{"payment-signature": true}}, {[]string{"x-unknown"}, []Header{{"x-unknown", "a"}}, nil}}
	for i, v := range cases {
		if _, e := Normalize(Request{Method: "GET", Headers: v.headers}, v.names, v.allow, 65536); e == nil {
			t.Fatal(i)
		}
	}
}
func TestDotSegmentsAndContentBoundary(t *testing.T) {
	for in, want := range map[string]string{"/a/b/../": "/a/", "/a//b/./": "/a//b/", "/../a": "/a", "/a/%2e%2e/b": "/b"} {
		c, e := Normalize(Request{Method: "GET", Path: in}, nil, nil, 1000)
		if e != nil || c.Path != want {
			t.Fatalf("%s: %+v %v", in, c, e)
		}
	}
	body := []byte{0x1f, 0x8b, 1}
	r := Request{Method: "POST", Body: body, Headers: []Header{{"content-encoding", "gzip"}}}
	c, e := Normalize(r, []string{"content-encoding"}, map[string]bool{"content-encoding": true}, 1000)
	if e != nil {
		t.Fatal(e)
	}
	before := c.Hash()
	body[2] = 2
	if c.Hash() != before {
		t.Fatal("aliased body")
	}
	if c.CheckRoute("/rewritten") == nil {
		t.Fatal("route mismatch accepted")
	}
	if _, e := Normalize(r, nil, nil, 1); e == nil {
		t.Fatal("limit")
	}
}

func TestNormalizedExpansionLimit(t *testing.T) {
	if _, e := Normalize(Request{Method: "GET", Query: "&"}, nil, nil, 4); e == nil {
		t.Fatal("normalized expansion exceeded limit")
	}
}
