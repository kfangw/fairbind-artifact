"""Local model execution with final-hidden-state capture.

Both the seller path and the verifier path load a Hugging Face causal language
model from a local directory (`local_files_only`, no remote code). The same code
runs the public checkpoint for a real run and the synthetic checkpoint written by
`write_synthetic_checkpoint` for offline tests.

The synthetic checkpoint is a Llama-architecture model with seeded random weights.
It has no tokenizer and produces no meaningful text. It exists because the test
environment has no network access to a public weight host and no accelerator; it
exercises the real model-loading, forward-pass and activation-capture code with
tensors of realistic shape (hidden size 576, as in SmolLM2-135M), not the
behaviour of a trained model.
"""
import hashlib
import os
from pathlib import Path

WEIGHT_MANIFEST_FORMAT = 'fairbind/experimental/weight-manifest/v1'
QUANTIZATIONS = ('none', 'int8-weight-rounding')
PRECISIONS = {'float32': 'float32', 'bfloat16': 'bfloat16'}
MODEL_FILE_SUFFIXES = ('.json', '.safetensors', '.model', '.txt', '.jinja')

# Shapes follow SmolLM2-135M except for depth and vocabulary size, which are
# reduced so that tests finish in seconds on one CPU thread.
SYNTHETIC_SHAPE = dict(vocab_size=4096, hidden_size=576, intermediate_size=1536,
                       num_hidden_layers=4, num_attention_heads=9, num_key_value_heads=3,
                       max_position_embeddings=2048, rms_norm_eps=1e-5, rope_theta=100000.0,
                       tie_word_embeddings=True)

def model_files(model_dir):
    """Regular files that make up a local checkpoint, excluding caches and locks."""
    root = Path(model_dir)
    files = sorted(p for p in root.iterdir() if p.is_file() and not p.is_symlink() and p.name.endswith(MODEL_FILE_SUFFIXES))
    if not any(p.name.endswith('.safetensors') for p in files):
        raise ValueError('no safetensors weights in model directory')
    return files

def weight_manifest(model_dir):
    """Content manifest whose canonical hash is the modelHash."""
    files = {}
    for path in model_files(model_dir):
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1 << 20), b''):
                digest.update(block)
        files[path.name] = digest.hexdigest()
    return {'format': WEIGHT_MANIFEST_FORMAT, 'version': 1, 'files': files}

def write_synthetic_checkpoint(directory, seed):
    """Write a seeded random Llama checkpoint. Deterministic for a fixed seed."""
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM
    os.makedirs(directory, exist_ok=False)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = LlamaForCausalLM(LlamaConfig(**SYNTHETIC_SHAPE))
    model.save_pretrained(directory, safe_serialization=True)
    return directory

def configure_runtime(threads):
    import torch
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)

def quantize_int8_rows(weight):
    """Symmetric per-output-row int8 rounding, dequantized back to the input dtype."""
    import torch
    w = weight.float()
    scale = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-12) / 127.0
    return (torch.clamp(torch.round(w / scale), -127, 127) * scale).to(weight.dtype)

def load_model(model_dir, precision, quantization, attention, device='cpu'):
    import torch
    from transformers import AutoModelForCausalLM
    if precision not in PRECISIONS or quantization not in QUANTIZATIONS:
        raise ValueError('unsupported precision or quantization')
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        dtype=getattr(torch, PRECISIONS[precision]), attn_implementation=attention).to(device).eval()
    if quantization == 'int8-weight-rounding':
        with torch.no_grad():
            for module in model.modules():
                if isinstance(module, torch.nn.Linear):
                    module.weight.copy_(quantize_int8_rows(module.weight))
    return model

def _forward(model, tokens):
    import torch
    ids = torch.tensor([tokens], dtype=torch.long, device=model.device)
    out = model(input_ids=ids, output_hidden_states=True, use_cache=False)
    return out.hidden_states[-1][0], out.logits[0]

def generate(model, prompt_ids, max_new_tokens):
    """Greedy decoding without a KV cache.

    Returns the generated token IDs and the TOPLOC activation list: the prefill
    final hidden states [prompt_len, hidden] followed by one [hidden] row for each
    decode step that consumed a generated token.
    """
    import torch
    if not prompt_ids or max_new_tokens < 1:
        raise ValueError('empty prompt or no tokens requested')
    tokens, generated, activations = list(prompt_ids), [], []
    with torch.inference_mode():
        for step in range(max_new_tokens):
            hidden, logits = _forward(model, tokens)
            activations.append(hidden if step == 0 else hidden[-1])
            nxt = int(logits[-1].argmax())
            generated.append(nxt)
            tokens.append(nxt)
    return generated, [a.to(torch.bfloat16).cpu().contiguous() for a in activations]

def reproduce(model, prompt_ids, output_ids, with_tokens=False):
    """Verifier prefill over prompt plus response, split into the same activation list.

    With with_tokens, also return the greedy token at every response position
    from the same forward pass (the prefix is the committed response, so this
    is the re-executed output under teacher forcing).
    """
    import torch
    if not prompt_ids or not output_ids:
        raise ValueError('empty prompt or response')
    with torch.inference_mode():
        hidden, logits = _forward(model, list(prompt_ids) + list(output_ids[:-1]))
    p = len(prompt_ids)
    rows = [hidden[:p]] + [hidden[p + j - 1] for j in range(1, len(output_ids))]
    rows = [a.to(torch.bfloat16).cpu().contiguous() for a in rows]
    if not with_tokens:
        return rows
    tokens = [int(t) for t in logits[p - 1:p - 1 + len(output_ids)].argmax(dim=-1)]
    return rows, tokens
