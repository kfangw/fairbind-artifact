package verifier

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/inference"
	gate "example.org/fairbind/runtime/verifier"
)

// WeightManifestFormat is the layout of runtime/inference/model.py
// weight_manifest; its canonical Keccak-256 is the modelHash.
const WeightManifestFormat = "fairbind/experimental/weight-manifest/v1"

var modelFileSuffixes = []string{".json", ".safetensors", ".model", ".txt", ".jinja"}

// NewPredicateRouter builds the predicate router of the verifier command from
// its configuration. The data pipeline is registered under the experimental
// decimal-median predicate when dataPredicate is configured, and the inference
// pipeline under OPEN_WEIGHTS_TOPLOC_V1 when inferencePredicate is configured.
// Every other identifier receives the INCONCLUSIVE fallback. The configured
// data manifests are stored in objects first, so that a fallback envelope for a
// class-1 profile can reference them.
func NewPredicateRouter(cfg Parsed, objects *evidence.Store, sig gate.CastVerifier, revision string) (PredicateRouter, error) {
	r := PredicateRouter{ByID: map[protocol.Bytes32]Predicate{}, Objects: objects, Revision: revision}
	if cfg.DataManifests != nil {
		dp, err := newDataPredicate(cfg, objects, sig, revision)
		if err != nil {
			return r, fmt.Errorf("dataPredicate: %w", err)
		}
		r.ByID[dataworker.PolicyID] = dp
	}
	if cfg.InferencePredicate != nil {
		ip, err := newInferencePredicate(cfg, objects, sig, revision)
		if err != nil {
			return r, fmt.Errorf("inferencePredicate: %w", err)
		}
		r.ByID[inference.PredicateID] = ip
	}
	return r, nil
}

func newDataPredicate(cfg Parsed, objects *evidence.Store, sig gate.CastVerifier, revision string) (DataPredicate, error) {
	rc := cfg.DataPredicate.References
	opt := refsource.VerifyOptions{AllowSynthetic: rc.AllowSynthetic}
	if rc.RootsFile != "" {
		pem, err := os.ReadFile(rc.RootsFile)
		if err != nil {
			return DataPredicate{}, err
		}
		opt.Roots = x509.NewCertPool()
		if !opt.Roots.AppendCertsFromPEM(pem) {
			return DataPredicate{}, fmt.Errorf("no certificates in %s", rc.RootsFile)
		}
	}
	registry := refsource.DefaultRegistry()
	for id, m := range cfg.DataManifests {
		for _, s := range m.Sources.Sources {
			if _, ok := registry[s]; !ok {
				return DataPredicate{}, fmt.Errorf("profile %d: source %q is not in the reference registry", id, s)
			}
		}
		for _, obj := range []any{m.Sources, m.Policy} {
			if _, err := put(objects, obj); err != nil {
				return DataPredicate{}, fmt.Errorf("profile %d: storing manifests: %w", id, err)
			}
		}
	}
	provider := refsource.Provider{Registry: registry, Verify: opt}
	switch rc.Mode {
	case "replay":
		replay, err := refsource.LoadReplay(rc.ReplayDir, opt)
		if err != nil {
			return DataPredicate{}, err
		}
		if len(replay.Objects) == 0 {
			return DataPredicate{}, fmt.Errorf("no raw objects in %s", rc.ReplayDir)
		}
		provider.Retriever = replay
	case "live":
		proxy, err := refsource.ProxyFromEnvironment()
		if err != nil {
			return DataPredicate{}, err
		}
		provider.Retriever = refsource.Live{Capturer: refsource.Capturer{Roots: opt.Roots, Timeout: cfg.DataTimeout, Proxy: proxy}}
		if rc.CaptureDir != "" {
			provider.Sink = &refsource.DirSink{Dir: rc.CaptureDir}
		}
	default:
		return DataPredicate{}, fmt.Errorf("unknown reference mode %q", rc.Mode)
	}
	return DataPredicate{
		Pipeline: dataworker.Pipeline{Signature: sig, References: provider, Decoder: refsource.Decoder{Registry: registry, Verify: opt}, Timeout: cfg.DataTimeout},
		Profiles: cfg.DataManifests, Objects: objects, Revision: revision,
	}, nil
}

func newInferencePredicate(cfg Parsed, objects *evidence.Store, sig gate.CastVerifier, revision string) (InferencePredicate, error) {
	c := cfg.InferencePredicate
	for _, f := range []string{c.Python, c.Script} {
		if st, err := os.Stat(f); err != nil || st.IsDir() {
			return InferencePredicate{}, fmt.Errorf("%s is not a file", f)
		}
	}
	model, err := ModelHash(c.ModelDir)
	if err != nil {
		return InferencePredicate{}, fmt.Errorf("modelDir: %w", err)
	}
	configs, err := LoadConfigManifests(c.ConfigDir)
	if err != nil {
		return InferencePredicate{}, fmt.Errorf("configDir: %w", err)
	}
	return InferencePredicate{
		Pipeline: inference.Pipeline{Signature: sig, Python: c.Python, Script: c.Script, Timeout: cfg.InferenceTimeout},
		Configs:  configs, Models: map[protocol.Bytes32]string{model: c.ModelDir}, Objects: objects, Revision: revision,
	}, nil
}

// ModelHash returns the modelHash of a local checkpoint directory: the
// Keccak-256 of the canonical weight manifest, which lists the SHA-256 of every
// regular .json, .safetensors, .model, .txt and .jinja file directly in dir
// (runtime/inference/model.py weight_manifest).
func ModelHash(dir string) (protocol.Bytes32, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return protocol.Bytes32{}, err
	}
	files := map[string]string{}
	weights := false
	for _, e := range entries {
		if !e.Type().IsRegular() || !hasModelSuffix(e.Name()) {
			continue
		}
		sum, err := fileSHA256(filepath.Join(dir, e.Name()))
		if err != nil {
			return protocol.Bytes32{}, err
		}
		files[e.Name()] = sum
		weights = weights || strings.HasSuffix(e.Name(), ".safetensors")
	}
	if !weights {
		return protocol.Bytes32{}, errors.New("no safetensors weights in model directory")
	}
	return WeightManifestHash(files)
}

// WeightManifestHash hashes a weight manifest given file name -> SHA-256 hex.
func WeightManifestHash(files map[string]string) (protocol.Bytes32, error) {
	raw, err := dataworker.CanonicalObject(map[string]any{"format": WeightManifestFormat, "version": 1, "files": files})
	if err != nil {
		return protocol.Bytes32{}, err
	}
	return protocol.Keccak256(raw), nil
}

// LoadConfigManifests reads every regular *.json file in dir, keyed by the
// Keccak-256 of its exact bytes (the configHash it can open).
func LoadConfigManifests(dir string) (map[protocol.Bytes32][]byte, error) {
	names, err := filepath.Glob(filepath.Join(dir, "*.json"))
	if err != nil {
		return nil, err
	}
	sort.Strings(names)
	out := map[protocol.Bytes32][]byte{}
	for _, n := range names {
		st, err := os.Lstat(n)
		if err != nil {
			return nil, err
		}
		if !st.Mode().IsRegular() {
			continue
		}
		raw, err := os.ReadFile(n)
		if err != nil {
			return nil, err
		}
		out[protocol.Keccak256(raw)] = raw
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no configuration manifests in %s", dir)
	}
	return out, nil
}

func hasModelSuffix(name string) bool {
	for _, s := range modelFileSuffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return false
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
