# 🧭 gortex Entegrasyon / Vendor Planı (Brownfield Milestone B)

> **Tarih:** 2026-06-19
> **Durum:** PLAN — kaynak henüz taşınmadı. Gerçek vendor işlemi **S5 sonrası, Milestone B** ile yapılacak.
> **İlgili:** `docs/05_expansion_vision.md`, memory `strategic-direction`, `cache.md`

---

## 0. Neden şimdi taşımıyoruz

Kullanıcı "entegrasyon = kaynak kodu repoya taşımak" dedi. gortex için bunu **şimdi** yapmıyoruz çünkü:

1. **Yol haritası kuralı:** `05_expansion_vision.md` → "S4/S5 sırasında brownfield/gortex yönünde refactor YOK". Sıradaki iş Sprint 5 (Security + Test Generator).
2. **Ölçek:** gortex **2.244 Go dosyası** (2.513 toplam). %98 Go, Go 1.26 + CGO + tree-sitter ile derleniyor.
3. **Mimari gerçek:** Kaynağı repoya koysak bile gortex **ayrı bir Go programı** olarak kalır — Python'a kütüphane gibi import edilmez. Yine derlenip binary üretilir; Python tarafı onunla **MCP (stdio) veya HTTP `/v1/*`** üzerinden konuşur. Yani "vendor" = repoya bir Go alt-projesi gömmek, "merge" değil.

gortex **greenfield için gereksiz** (ürettiğimiz tüm kod zaten elimizde); değeri **brownfield modunda** (mevcut repoyu anlama: symbol/dependency graph, impact/blast-radius).

---

## 1. Kaynak gerçeği (incelenen commit)

- Repo: https://github.com/zzet/gortex — Apache-2.0, Copyright 2024–2026 Andrey Kumanyaev
- Yapı: `cmd/gortex/` (CLI), `pkg/gortex/` (public lib), `internal/` (private), `docs/`, `bench/`, `eval/`, `examples/`, `scripts/`, `go.mod`/`go.sum`, `Makefile`, `NOTICE`, `THIRD_PARTY_NOTICES.md`
- Özellikler: tree-sitter (257 dil), kalıcı knowledge graph, blast-radius, 100+ MCP tool, GloVe-50d semantic search, web UI (force-directed graph), opsiyonel LLM entegrasyonu.

---

## 2. Vendor stratejisi seçenekleri (Milestone B'de karar)

| Seçenek | Nasıl | Artı | Eksi |
|---|---|---|---|
| **A. git subtree** | gortex'i `external/gortex/` altına subtree olarak çek | Tam kaynak repoda; upstream'den `subtree pull` ile güncellenebilir; tek repo | 2.5k dosya repo'ya girer; ayrı Go toolchain |
| **B. Fork + submodule** | Kendi fork'umuz, repoya submodule | Fork'ta serbest revizyon; ana repo şişmez | Submodule yönetimi; CI'da ekstra checkout |
| **C. Binary + thin client** | Kaynağı taşıma; `gortex` binary'sini indir, Python'dan MCP/HTTP ile kullan | En hafif; Python tarafı temiz | "Kaynağı taşımak" hedefini karşılamaz |

> Kullanıcı kaynağı repoda istediği için varsayılan **A (git subtree → `external/gortex/`)**, gerekirse fork'a (B) geçiş. Hangisi olursa olsun Apache-2.0 `LICENSE` + `NOTICE` + `THIRD_PARTY_NOTICES.md` korunur ve değişiklikler `NOTICE`'ta belirtilir.

---

## 3. Python ↔ gortex köprüsü (Milestone B mimarisi)

```
Brownfield entry point
  └─ RepoIngestor (yeni)
       └─ gortex daemon (Go binary, external/gortex'ten derlenir)
            ├─ MCP (stdio)  ──┐
            └─ HTTP /v1/*  ───┤→  src/integrations/gortex_client.py (yeni, Python)
                               └→  symbol graph / impact / blast-radius
  └─ ArchitectAgent (brownfield modu): impact analizi → diff planı
  └─ Reviewer agent (S6): tüm dosyaları okumak yerine gortex impact sorgusu
```

Yeni Python tarafı:
- `src/integrations/gortex_client.py` — daemon yaşam döngüsü (`gortex daemon start --detach`) + MCP/HTTP istemci sarmalayıcı (boundary Pydantic modelleri ile).
- `src/brownfield/repo_ingestor.py` — repo tarama, gortex'e track ettirme.
- Reviewer/Architect agent'larına "impact query" tool'u.

---

## 4. Yapılacaklar (Milestone B açıldığında)

- [ ] Seçenek A/B kararı (subtree vs fork+submodule).
- [ ] `external/gortex/` vendor (Apache-2.0 NOTICE korunarak).
- [ ] Go toolchain'i CI'a ekle (Go 1.26 + CGO) — gortex binary build job.
- [ ] `src/integrations/gortex_client.py` + boundary modelleri + testler.
- [ ] Brownfield entry point + `RepoIngestor`.
- [ ] `mypy --strict` ve mevcut kalite kapıları korunur.

## 5. Lisans / uyum notu
gortex **Apache-2.0**; superpowers **MIT**. İkisi de bizim kullanımımıza uygun. Vendor edilen her kaynak için orijinal LICENSE/NOTICE dosyaları repoda tutulur ve yapılan değişiklikler işaretlenir.
