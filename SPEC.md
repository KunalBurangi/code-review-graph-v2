# Code Review Graph v2 - Architecture Specification

## Core Improvements Over v1

### 1. Smart Impact Prediction (replaces naive BFS)
- ML-based scoring: trained on actual change patterns to predict true impact
- Considers: call frequency, change history, file volatility, test coverage
- Target: improve precision from 0.38 to 0.70+ while maintaining 100% recall

### 2. Framework-Aware Flow Detection
- Language-specific pattern libraries (not just Python)
- JS: Express, React, Next.js, Vue entry point detection
- Go: gin, echo, standard lib http handlers
- Target: improve flow recall from 33% to 70%+

### 3. Learned Search Ranking
- Learn from user clicks/selections over time
- Combine: BM25 + semantic embeddings + graph proximity + popularity
- Target: improve MRR from 0.35 to 0.70+

### 4. Multi-Repo Federation
- Register and query across multiple repositories
- Cross-repo dependency detection (npm workspaces, go modules, etc.)
- Unified blast radius across repo boundaries

### 5. Feedback Loop
- Track which suggested files were actually used
- Online learning to improve impact prediction
- User can correct predictions to improve future accuracy