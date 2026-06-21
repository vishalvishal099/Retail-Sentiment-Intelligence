# Vision Pipeline Evaluation

Reproducible evidence that the multi-pass captioning fix eliminates hallucination.

## Quick Start

```bash
# 1. Start Ollama
ollama serve

# 2. Pull the model (one-time, 3.3 GB)
ollama pull gemma3:4b

# 3. Run the notebook
jupyter notebook vision_evaluation.ipynb
# → Click "Run All Cells"
```

**No Ollama?** The notebook loads cached results from `data/benchmark_25_results.json` as a fallback.

## What's Inside

| File | Purpose |
|------|---------|
| `vision_evaluation.ipynb` | Main evaluation notebook — Run All to reproduce results |
| `ground_truth.json` | Human-annotated truth for 25 test images |
| `results/` | Timestamped JSON exports from each run |

## What the Notebook Shows

1. **25 real Reddit images** displayed as thumbnails
2. **Single-pass** (old method) output — with hallucinations highlighted in red
3. **Multi-pass** (our fix) output — zero hallucination
4. **Side-by-side table** — image + ground truth + before + after + verdict + comment
5. **Automated hallucination detection** — counts false receipts, false damage, invented products
6. **Summary metrics** — hallucination rate, pass rate, latency comparison
7. **Exportable JSON** — timestamped evidence for dissertation submission

## Key Result

| Metric | Single-Pass (Old) | Multi-Pass (Fix) |
|--------|-------------------|------------------|
| Hallucination rate | 44% | **0%** |
| False receipt claims | 5/25 | 0/25 |
| False damage claims | 10/25 | 0/25 |
| Pass rate | 56% | **88%** |
| Avg latency | 3.5s | 9.6s |

## Source Code

The multi-pass algorithm lives in `src/analysis/vision.py`:
- `caption_enhanced()` — orchestrates the 4-pass pipeline
- `STRUCTURE_PROMPT` — Pass 1: identify image type
- `TILE_TEXT_PROMPT` — Pass 3: read text from each crop
- `MERGE_PROMPT` — Pass 4: combine without image (anti-hallucination)
- `_create_tiles()` — aspect-ratio-aware grid splitting
