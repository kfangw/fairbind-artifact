package verifier

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/inference"
	gate "example.org/fairbind/runtime/verifier"
)

const replayFixtures = "../../runtime/dataworker/testdata/refsource/replay"

func baseConfig() map[string]any {
	return map[string]any{
		"rpcUrl": "http://127.0.0.1:8545", "chainId": 31337, "contract": "0x1111111111111111111111111111111111111111",
		"verifierId": 3, "keystore": "k", "passwordFile": "p", "castPath": "cast", "stateDir": "s",
		"pollIntervalSeconds": 1, "startBlock": 0, "submitMarginBlocks": 4,
		"relay":    map[string]any{"from": "0x2222222222222222222222222222222222222222", "gas": 3000000},
		"sellers":  map[string]any{"7": "http://127.0.0.1:18401"},
		"profiles": map[string]any{"3": map[string]any{}},
	}
}

// writeManifests writes the policy and source set of the replay fixtures and
// returns their paths and canonical hashes.
func writeManifests(t *testing.T) (policyFile, setFile string, ph, sh protocol.Bytes32) {
	t.Helper()
	dir := t.TempDir()
	policy := dataworker.Policy{Sources: []string{coinbaseSource, krakenSource}, Quorum: 2, ReferenceTime: pipelineRefTime, MaxSkew: 30,
		Fields: map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "50"}}}
	set := dataworker.SourceSet{Sources: policy.Sources}
	ph, _ = dataworker.ObjectHash(policy)
	sh, _ = dataworker.ObjectHash(set)
	policyFile, setFile = filepath.Join(dir, "policy.json"), filepath.Join(dir, "sources.json")
	for path, v := range map[string]any{policyFile: policy, setFile: set} {
		raw, _ := json.MarshalIndent(v, "", "  ")
		if err := os.WriteFile(path, raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return
}

func parse(t *testing.T, c map[string]any) (Parsed, error) {
	t.Helper()
	raw, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	return ParseConfig(raw)
}

func TestConfigWithoutPipelines(t *testing.T) {
	p, err := parse(t, baseConfig())
	if err != nil {
		t.Fatal(err)
	}
	if p.DataManifests != nil || p.InferencePredicate != nil {
		t.Fatal("pipelines configured by default")
	}
	objects, _ := evidence.NewStore(t.TempDir(), 1<<20)
	r, err := NewPredicateRouter(p, objects, gate.CastVerifier{}, "test")
	if err != nil || len(r.ByID) != 0 || r.Objects != objects {
		t.Fatal(r, err)
	}
}

func TestConfigDataPredicate(t *testing.T) {
	policyFile, setFile, ph, sh := writeManifests(t)
	c := baseConfig()
	c["profiles"] = map[string]any{"3": map[string]any{"sourceSetHash": hex32(sh), "tolerancePolicyHash": hex32(ph)}}
	c["dataPredicate"] = map[string]any{
		"references": map[string]any{"mode": "replay", "replayDir": replayFixtures, "allowSynthetic": true},
		"profiles":   map[string]any{"3": map[string]any{"policyFile": policyFile, "sourceSetFile": setFile}},
	}
	p, err := parse(t, c)
	if err != nil {
		t.Fatal(err)
	}
	m, ok := p.DataManifests[3]
	if !ok || m.Policy.Quorum != 2 || len(m.Sources.Sources) != 2 || p.DataTimeout.Seconds() != 15 {
		t.Fatalf("%+v %v", p.DataManifests, p.DataTimeout)
	}
	objects, _ := evidence.NewStore(t.TempDir(), 1<<20)
	r, err := NewPredicateRouter(p, objects, gate.CastVerifier{}, "test")
	if err != nil {
		t.Fatal(err)
	}
	dp, ok := r.ByID[dataworker.PolicyID].(DataPredicate)
	if !ok || len(r.ByID) != 1 || dp.Pipeline.References == nil || dp.Pipeline.Decoder == nil {
		t.Fatalf("%+v", r.ByID)
	}
	if dataworker.PolicyID != gate.ExperimentalDataPredicate {
		t.Fatal("data pipeline is not registered under the experimental predicate")
	}
	// The manifests are in the store for fallback envelopes.
	for _, h := range []protocol.Bytes32{ph, sh} {
		if _, err := objects.Get(h); err != nil {
			t.Fatal("manifest not stored", hex32(h), err)
		}
	}
}

func TestConfigDataPredicateRejects(t *testing.T) {
	policyFile, setFile, ph, _ := writeManifests(t)
	junk := filepath.Join(t.TempDir(), "junk.json")
	os.WriteFile(junk, []byte(`{"source_ids":[],"extra":1}`), 0o644)
	good := func() map[string]any {
		return map[string]any{
			"references": map[string]any{"mode": "replay", "replayDir": replayFixtures, "allowSynthetic": true},
			"profiles":   map[string]any{"3": map[string]any{"policyFile": policyFile, "sourceSetFile": setFile}},
		}
	}
	for name, c := range map[string]struct {
		edit func(d map[string]any, root map[string]any)
		want string
	}{
		"unknown mode":        {func(d, _ map[string]any) { d["references"].(map[string]any)["mode"] = "fixture" }, "mode must be"},
		"replay without dir":  {func(d, _ map[string]any) { delete(d["references"].(map[string]any), "replayDir") }, "replay mode needs replayDir"},
		"live with replayDir": {func(d, _ map[string]any) { d["references"].(map[string]any)["mode"] = "live" }, "live mode takes no replayDir"},
		"no profiles":         {func(d, _ map[string]any) { d["profiles"] = map[string]any{} }, "at least one profile"},
		"profile id zero": {func(d, _ map[string]any) {
			d["profiles"] = map[string]any{"0": map[string]any{"policyFile": policyFile, "sourceSetFile": setFile}}
		}, "invalid profile id"},
		"missing file": {func(d, _ map[string]any) {
			d["profiles"] = map[string]any{"3": map[string]any{"policyFile": policyFile}}
		}, "policyFile and sourceSetFile are required"},
		"unknown policy member": {func(d, _ map[string]any) {
			d["profiles"] = map[string]any{"3": map[string]any{"policyFile": junk, "sourceSetFile": setFile}}
		}, "unknown field"},
		"negative timeout": {func(d, _ map[string]any) { d["timeoutSeconds"] = -1 }, "timeoutSeconds"},
		"unknown member":   {func(d, _ map[string]any) { d["provider"] = "x" }, "unknown field"},
		"binding mismatch": {func(_, root map[string]any) {
			root["profiles"] = map[string]any{"3": map[string]any{"tolerancePolicyHash": hex32(protocol.Keccak256([]byte("other")))}}
		}, "differs from profiles[3].tolerancePolicyHash"},
		"source set binding mismatch": {func(_, root map[string]any) {
			root["profiles"] = map[string]any{"3": map[string]any{"tolerancePolicyHash": hex32(ph), "sourceSetHash": hex32(ph)}}
		}, "differs from profiles[3].sourceSetHash"},
	} {
		t.Run(name, func(t *testing.T) {
			root, d := baseConfig(), good()
			c.edit(d, root)
			root["dataPredicate"] = d
			if _, err := parse(t, root); err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("got %v, want %q", err, c.want)
			}
		})
	}
}

func TestConfigDataPredicateBuildRejects(t *testing.T) {
	policyFile, setFile, _, _ := writeManifests(t)
	c := baseConfig()
	c["dataPredicate"] = map[string]any{
		"references": map[string]any{"mode": "replay", "replayDir": t.TempDir(), "allowSynthetic": true},
		"profiles":   map[string]any{"3": map[string]any{"policyFile": policyFile, "sourceSetFile": setFile}},
	}
	p, err := parse(t, c)
	if err != nil {
		t.Fatal(err)
	}
	objects, _ := evidence.NewStore(t.TempDir(), 1<<20)
	if _, err = NewPredicateRouter(p, objects, gate.CastVerifier{}, "test"); err == nil || !strings.Contains(err.Error(), "no raw objects") {
		t.Fatal("empty replay directory accepted:", err)
	}
	// A source outside the reference registry is refused at startup.
	p.DataManifests[3] = DataManifests{Sources: dataworker.SourceSet{Sources: []string{"example:ticker"}}}
	if _, err = NewPredicateRouter(p, objects, gate.CastVerifier{}, "test"); err == nil || !strings.Contains(err.Error(), "not in the reference registry") {
		t.Fatal("unregistered source accepted:", err)
	}
}

func TestConfigInferencePredicate(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 not on PATH")
	}
	script, _ := filepath.Abs("../../runtime/inference/evaluate.py")
	model, configs := t.TempDir(), t.TempDir()
	os.WriteFile(filepath.Join(model, "config.json"), []byte(`{"a":1}`), 0o644)
	os.WriteFile(filepath.Join(model, "model.safetensors"), []byte("weights"), 0o644)
	os.WriteFile(filepath.Join(model, "notes.bin"), []byte("ignored"), 0o644)
	cfgBytes := []byte(`{"format":"x"}`)
	os.WriteFile(filepath.Join(configs, "c.json"), cfgBytes, 0o644)
	c := baseConfig()
	c["inferencePredicate"] = map[string]any{"python": python, "script": script, "modelDir": model, "configDir": configs, "timeoutSeconds": 30}
	p, err := parse(t, c)
	if err != nil {
		t.Fatal(err)
	}
	if p.InferenceTimeout.Seconds() != 30 {
		t.Fatal(p.InferenceTimeout)
	}
	objects, _ := evidence.NewStore(t.TempDir(), 1<<20)
	r, err := NewPredicateRouter(p, objects, gate.CastVerifier{}, "test")
	if err != nil {
		t.Fatal(err)
	}
	ip, ok := r.ByID[inference.PredicateID].(InferencePredicate)
	if !ok || len(r.ByID) != 1 || ip.Pipeline.Python != python || ip.Pipeline.Script != script {
		t.Fatalf("%+v", r.ByID)
	}
	sum := func(b string) string { raw, _ := fileSHA256Bytes([]byte(b)); return raw }
	want, _ := WeightManifestHash(map[string]string{"config.json": sum(`{"a":1}`), "model.safetensors": sum("weights")})
	if _, ok := ip.Models[want]; !ok {
		t.Fatal("model directory not keyed by its weight manifest hash")
	}
	if len(ip.Models) != 1 || string(ip.Configs[protocol.Keccak256(cfgBytes)]) != string(cfgBytes) {
		t.Fatalf("%+v %+v", ip.Models, ip.Configs)
	}
	for h, dir := range ip.Models {
		if got, _ := ModelHash(model); got != h || dir != model {
			t.Fatal("model hash", hex32(h), dir)
		}
	}

	for name, edit := range map[string]func(m map[string]any){
		"missing python":   func(m map[string]any) { delete(m, "python") },
		"missing modelDir": func(m map[string]any) { delete(m, "modelDir") },
		"negative timeout": func(m map[string]any) { m["timeoutSeconds"] = -5 },
	} {
		t.Run(name, func(t *testing.T) {
			root := baseConfig()
			m := map[string]any{"python": python, "script": script, "modelDir": model, "configDir": configs}
			edit(m)
			root["inferencePredicate"] = m
			if _, err := parse(t, root); err == nil {
				t.Fatal("accepted")
			}
		})
	}
	// Directories that hold no weights or no manifests are refused at startup.
	for name, m := range map[string]map[string]any{
		"no weights":   {"python": python, "script": script, "modelDir": configs, "configDir": configs},
		"no manifests": {"python": python, "script": script, "modelDir": model, "configDir": t.TempDir()},
	} {
		t.Run(name, func(t *testing.T) {
			root := baseConfig()
			root["inferencePredicate"] = m
			p, err := parse(t, root)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = NewPredicateRouter(p, objects, gate.CastVerifier{}, "test"); err == nil {
				t.Fatal("accepted")
			}
		})
	}
}

// The Go weight manifest hash equals the modelHash the Python binding
// computed for the synthetic checkpoint fixture.
func TestWeightManifestHashMatchesFixture(t *testing.T) {
	raw, err := os.ReadFile("../../runtime/inference/testdata/binding-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		WeightManifest struct {
			Files map[string]string `json:"files"`
		} `json:"weightManifest"`
		Preimage map[string]string `json:"preimage"`
	}
	if err = json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	h, err := WeightManifestHash(fx.WeightManifest.Files)
	if err != nil || hex32(h) != fx.Preimage["modelHash"] {
		t.Fatal(hex32(h), fx.Preimage["modelHash"], err)
	}
}

func fileSHA256Bytes(b []byte) (string, error) {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:]), nil
}
