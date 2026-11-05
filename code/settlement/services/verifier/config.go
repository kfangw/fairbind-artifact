package verifier

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/ledger"
)

// ProfileBindings are the manifest hashes expected for one service profile.
type ProfileBindings struct {
	SourceSetHash       string `json:"sourceSetHash,omitempty"`
	TolerancePolicyHash string `json:"tolerancePolicyHash,omitempty"`
	ModelHash           string `json:"modelHash,omitempty"`
	ConfigHash          string `json:"configHash,omitempty"`
}

// RelayConfig configures the loopback development relay (judgment.LocalRelay).
type RelayConfig struct {
	URL  string `json:"url,omitempty"` // defaults to rpcUrl
	From string `json:"from"`
	Gas  uint64 `json:"gas"`
}

// DataProfileConfig names the operator's source set and tolerance policy files
// for one class-1 profile. Both are JSON objects in the dataworker layouts
// (SourceSet, Policy); their canonical hashes are the committed manifest hashes.
type DataProfileConfig struct {
	PolicyFile    string `json:"policyFile"`
	SourceSetFile string `json:"sourceSetFile"`
}

// ReferenceConfig selects the reference provider of the data predicate. Source
// identifiers always resolve through refsource.DefaultRegistry; configuration
// never supplies an endpoint.
//
//   - mode "replay" serves saved raw objects from replayDir (no network).
//     allowSynthetic accepts the synthetic fixtures, which carry no TLS chain.
//   - mode "live" captures each source over HTTPS now. captureDir, if set,
//     retains every captured raw object.
//
// rootsFile optionally replaces the system roots (PEM) for chain validation.
type ReferenceConfig struct {
	Mode           string `json:"mode"`
	ReplayDir      string `json:"replayDir,omitempty"`
	AllowSynthetic bool   `json:"allowSynthetic,omitempty"`
	RootsFile      string `json:"rootsFile,omitempty"`
	CaptureDir     string `json:"captureDir,omitempty"`
}

// DataPredicateConfig registers the class-1 data pipeline
// (runtime/dataworker.Pipeline) under the experimental decimal-median predicate.
type DataPredicateConfig struct {
	TimeoutSeconds int                          `json:"timeoutSeconds,omitempty"`
	References     ReferenceConfig              `json:"references"`
	Profiles       map[string]DataProfileConfig `json:"profiles"`
}

// InferencePredicateConfig registers the class-2 re-execution pipeline
// (runtime/inference.Pipeline). modelDir is one local checkpoint directory; its
// modelHash is the weight manifest hash computed at startup. Every *.json file
// in configDir is a configuration manifest keyed by the Keccak-256 of its exact
// bytes.
type InferencePredicateConfig struct {
	Python         string `json:"python"`
	Script         string `json:"script"`
	ModelDir       string `json:"modelDir"`
	ConfigDir      string `json:"configDir"`
	TimeoutSeconds int    `json:"timeoutSeconds,omitempty"`
}

// Config is the JSON configuration file of the verifier process.
type Config struct {
	RPCURL              string                     `json:"rpcUrl"`
	ChainID             uint64                     `json:"chainId"`
	Contract            string                     `json:"contract"`
	VerifierID          uint32                     `json:"verifierId"`
	Keystore            string                     `json:"keystore"`
	PasswordFile        string                     `json:"passwordFile"`
	CastPath            string                     `json:"castPath"`
	StateDir            string                     `json:"stateDir"`
	PollIntervalSeconds int                        `json:"pollIntervalSeconds"`
	RPCTimeoutSeconds   int                        `json:"rpcTimeoutSeconds,omitempty"`
	StartBlock          uint64                     `json:"startBlock"`
	MaxLogRange         uint64                     `json:"maxLogRange,omitempty"`
	SubmitMarginBlocks  uint64                     `json:"submitMarginBlocks"`
	MaxEvidenceBytes    int64                      `json:"maxEvidenceBytes,omitempty"`
	MaxClaimsBytes      int                        `json:"maxClaimsBytes,omitempty"`
	Relay               RelayConfig                `json:"relay"`
	Sellers             map[string]string          `json:"sellers"`
	Profiles            map[string]ProfileBindings `json:"profiles"`
	// Optional predicate pipelines. A predicate identifier without a
	// configured pipeline receives the INCONCLUSIVE fallback.
	DataPredicate      *DataPredicateConfig      `json:"dataPredicate,omitempty"`
	InferencePredicate *InferencePredicateConfig `json:"inferencePredicate,omitempty"`
}

// Parsed holds validated, typed configuration values.
type Parsed struct {
	Config
	ContractAddr protocol.Address
	RelayFrom    protocol.Address
	Poll         time.Duration
	RPCTimeout   time.Duration
	SellerURLs   map[uint32]string
	Bindings     map[uint32]ledger.ManifestBindings
	// DataManifests holds the loaded source set and policy per profile when
	// dataPredicate is configured.
	DataManifests    map[uint32]DataManifests
	DataTimeout      time.Duration
	InferenceTimeout time.Duration
}

func LoadConfig(path string) (Parsed, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Parsed{}, err
	}
	return ParseConfig(raw)
}

func ParseConfig(raw []byte) (Parsed, error) {
	var p Parsed
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p.Config); err != nil {
		return p, fmt.Errorf("config: %w", err)
	}
	c := &p.Config
	var err error
	if _, err = checkEndpoint(c.RPCURL); err != nil {
		return p, fmt.Errorf("config rpcUrl: %w", err)
	}
	if p.ContractAddr, err = parseAddress(c.Contract); err != nil || p.ContractAddr == (protocol.Address{}) {
		return p, fmt.Errorf("config contract: invalid address")
	}
	if c.ChainID == 0 || c.VerifierID == 0 {
		return p, fmt.Errorf("config: chainId and verifierId are required")
	}
	if c.Keystore == "" || c.PasswordFile == "" || c.CastPath == "" || c.StateDir == "" {
		return p, fmt.Errorf("config: keystore, passwordFile, castPath and stateDir are required")
	}
	if c.PollIntervalSeconds <= 0 {
		return p, fmt.Errorf("config: pollIntervalSeconds must be positive")
	}
	p.Poll = time.Duration(c.PollIntervalSeconds) * time.Second
	if c.RPCTimeoutSeconds <= 0 {
		c.RPCTimeoutSeconds = 10
	}
	p.RPCTimeout = time.Duration(c.RPCTimeoutSeconds) * time.Second
	if c.MaxLogRange == 0 {
		c.MaxLogRange = 2000
	}
	if c.MaxEvidenceBytes == 0 {
		c.MaxEvidenceBytes = 4 << 20
	}
	if c.MaxClaimsBytes == 0 {
		c.MaxClaimsBytes = 65536
	}
	if c.Relay.URL == "" {
		c.Relay.URL = c.RPCURL
	}
	if p.RelayFrom, err = parseAddress(c.Relay.From); err != nil || p.RelayFrom == (protocol.Address{}) || c.Relay.Gas == 0 {
		return p, fmt.Errorf("config relay: from address and gas are required")
	}
	p.SellerURLs = map[uint32]string{}
	for k, v := range c.Sellers {
		id, err := strconv.ParseUint(k, 10, 32)
		if err != nil || id == 0 {
			return p, fmt.Errorf("config sellers: invalid seller id %q", k)
		}
		if _, err = checkEndpoint(v); err != nil {
			return p, fmt.Errorf("config sellers[%s]: %w", k, err)
		}
		p.SellerURLs[uint32(id)] = v
	}
	p.Bindings = map[uint32]ledger.ManifestBindings{}
	for k, v := range c.Profiles {
		id, err := strconv.ParseUint(k, 10, 32)
		if err != nil || id == 0 {
			return p, fmt.Errorf("config profiles: invalid profile id %q", k)
		}
		var m ledger.ManifestBindings
		for _, f := range []struct {
			s string
			d *protocol.Bytes32
		}{{v.SourceSetHash, &m.SourceSetHash}, {v.TolerancePolicyHash, &m.TolerancePolicyHash}, {v.ModelHash, &m.ModelHash}, {v.ConfigHash, &m.ConfigHash}} {
			if f.s == "" {
				continue
			}
			if *f.d, err = parse32(f.s); err != nil {
				return p, fmt.Errorf("config profiles[%s]: %w", k, err)
			}
		}
		p.Bindings[uint32(id)] = m
	}
	if err = p.parseDataPredicate(); err != nil {
		return p, err
	}
	if err = p.parseInferencePredicate(); err != nil {
		return p, err
	}
	return p, nil
}

func (p *Parsed) parseDataPredicate() error {
	d := p.Config.DataPredicate
	if d == nil {
		return nil
	}
	if d.TimeoutSeconds < 0 {
		return fmt.Errorf("config dataPredicate: timeoutSeconds must not be negative")
	}
	if d.TimeoutSeconds == 0 {
		d.TimeoutSeconds = 15
	}
	p.DataTimeout = time.Duration(d.TimeoutSeconds) * time.Second
	r := d.References
	switch r.Mode {
	case "replay":
		if r.ReplayDir == "" || r.CaptureDir != "" {
			return fmt.Errorf("config dataPredicate.references: replay mode needs replayDir and takes no captureDir")
		}
	case "live":
		if r.ReplayDir != "" || r.AllowSynthetic {
			return fmt.Errorf("config dataPredicate.references: live mode takes no replayDir or allowSynthetic")
		}
	default:
		return fmt.Errorf("config dataPredicate.references: mode must be \"replay\" or \"live\"")
	}
	if len(d.Profiles) == 0 {
		return fmt.Errorf("config dataPredicate: at least one profile is required")
	}
	p.DataManifests = map[uint32]DataManifests{}
	for k, v := range d.Profiles {
		id, err := strconv.ParseUint(k, 10, 32)
		if err != nil || id == 0 {
			return fmt.Errorf("config dataPredicate.profiles: invalid profile id %q", k)
		}
		if v.PolicyFile == "" || v.SourceSetFile == "" {
			return fmt.Errorf("config dataPredicate.profiles[%s]: policyFile and sourceSetFile are required", k)
		}
		var m DataManifests
		if err = readStrict(v.PolicyFile, &m.Policy); err != nil {
			return fmt.Errorf("config dataPredicate.profiles[%s] policyFile: %w", k, err)
		}
		if err = readStrict(v.SourceSetFile, &m.Sources); err != nil {
			return fmt.Errorf("config dataPredicate.profiles[%s] sourceSetFile: %w", k, err)
		}
		ph, err := dataworker.ObjectHash(m.Policy)
		if err != nil {
			return fmt.Errorf("config dataPredicate.profiles[%s] policyFile: %w", k, err)
		}
		sh, err := dataworker.ObjectHash(m.Sources)
		if err != nil {
			return fmt.Errorf("config dataPredicate.profiles[%s] sourceSetFile: %w", k, err)
		}
		// The manifests must be the ones the ledger adapter expects, when the
		// profile's bindings name them.
		if b, ok := p.Bindings[uint32(id)]; ok {
			if b.TolerancePolicyHash != (protocol.Bytes32{}) && b.TolerancePolicyHash != ph {
				return fmt.Errorf("config dataPredicate.profiles[%s]: policy hash %s differs from profiles[%s].tolerancePolicyHash", k, hex32(ph), k)
			}
			if b.SourceSetHash != (protocol.Bytes32{}) && b.SourceSetHash != sh {
				return fmt.Errorf("config dataPredicate.profiles[%s]: source set hash %s differs from profiles[%s].sourceSetHash", k, hex32(sh), k)
			}
		}
		p.DataManifests[uint32(id)] = m
	}
	return nil
}

func (p *Parsed) parseInferencePredicate() error {
	c := p.Config.InferencePredicate
	if c == nil {
		return nil
	}
	if c.Python == "" || c.Script == "" || c.ModelDir == "" || c.ConfigDir == "" {
		return fmt.Errorf("config inferencePredicate: python, script, modelDir and configDir are required")
	}
	if c.TimeoutSeconds < 0 {
		return fmt.Errorf("config inferencePredicate: timeoutSeconds must not be negative")
	}
	if c.TimeoutSeconds == 0 {
		c.TimeoutSeconds = 600
	}
	p.InferenceTimeout = time.Duration(c.TimeoutSeconds) * time.Second
	return nil
}

// readStrict decodes one JSON value from path, rejecting unknown fields and
// trailing data.
func readStrict(path string, v any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err = dec.Decode(v); err != nil {
		return err
	}
	if dec.More() {
		return fmt.Errorf("trailing data")
	}
	return nil
}
