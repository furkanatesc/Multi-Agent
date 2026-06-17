# 🚀 Genişleme Vizyonu: Mobil'in Ötesine + Brownfield Modu

> **Tarih:** 17 Haziran 2026
> **Durum:** Stratejik yön — **Sprint 4 bittikten sonra** ele alınacak. Bu dokümanın amacı vizyonu kayıt altına almak; mevcut sprint'lerde (S4/S5) bu yönde refactor **yapılmayacak**.
> **İlgili:** `cache.md`, memory `strategic-direction.md`

---

## 1. Motivasyon

Sistem şu an "Multi-Agent **Mobil** Uygulama Geliştirme" olarak adlandırılıyor. Ancak hedef daha geniş: yalnızca mobil değil; **masaüstü, web, terminal (CLI) tool'ları ve (yetkili bağlamda) güvenlik araçları** da üretebilen genel amaçlı bir otonom kod üretim platformu.

Ek olarak iki çalışma modu hedefleniyor:
- **Greenfield** (mevcut): sıfırdan proje üretimi.
- **Brownfield** (yeni): var olan bir repo üzerinde **refactor / feature ekleme**.

---

## 2. Temel İçgörü: Çekirdek Zaten Domain-Agnostik

Genişleme bir **yeniden yazım değil, bir soyutlama** işidir. Mevcut kodda:

| Genel (her domain'e çalışır) | Mobil'e bağlı (ince config katmanı) |
|---|---|
| LiteLLM client + fallback + cost tracking | `Platform = Literal["react-native", "flutter", ...]` (`state.py`) |
| LangGraph pipeline: architect→coder→inner_loop→security→review→deploy | Architect heuristic'leri + folder layout'ları (`agents/architect/tools.py`) |
| Checkpointing, inner/outer loop, HITL, guardrails | `Dockerfile.node` / `Dockerfile.dart` (planlanan) |
| `LiteLLMChatModel` köprüsü (S4) | Prompt'lar (`config/prompts/*.md`) |

Soldaki sütun değişmeden kalır; genişleme sağdaki ince katmanı **pluggable** hale getirmekten ibarettir.

---

## 3. Roadmap (Sıralı — her biri ayrı milestone)

### Milestone A — `TargetProfile` Soyutlaması (Greenfield genelleme)
`Platform` enum'u yerine pluggable bir **`TargetProfile` / "domain pack"** kavramı. Her profil şunları tanımlar:
- desteklenen platform/değerler,
- architect heuristic'leri,
- folder layout şablonu,
- Docker runtime image'ı,
- lint/test komutları.

Mobil bu profillerden **yalnızca biri** olur. Eklenecekler: **web, desktop, CLI tool**. Önemli: ad-hoc `if mobile/else` dalları değil, **temiz bir profil arayüzü**.

> ⚠️ **Güvenlik/"exploit" profili:** yalnızca **bilinçli olarak kapsamı çizilmiş** bir profil olarak — yetkili güvenlik testi, savunma, CTF veya eğitim bağlamında. Açık uçlu, hedef-belirsiz otonom saldırı aracı üretimi kapsam dışıdır.

### Milestone B — Brownfield Modu (Refactor / Feature Ekleme)
Greenfield'den **farklı bir çalışma modu**: önce mevcut kodu *anlamak* gerekir.
- repo ingestion (var olan kod tabanını okuma),
- symbol / dependency graph çıkarımı,
- impact / blast-radius analizi,
- doğrudan kod üretimi yerine **diff** üretimi,
- yeni giriş noktası (greenfield pipeline'ından ayrı).

Bu, profil eklemekten **daha büyük** bir stratejik genişlemedir.

---

## 4. gortex Entegrasyonu

[gortex](https://github.com/zzet/gortex) — Go tabanlı code-intelligence motoru (symbol/dependency graph, impact/blast-radius, MCP server, Apache-2.0, aktif).

- **Greenfield için uygun değil** (tüm üretilen kod zaten elimizde).
- **Brownfield modu için doğrudan ilgili** — symbol-graph / impact-analysis yaklaşımı tam buraya oturur.
- **Plan:** gortex'i olduğu gibi tüketmek yerine **kendimize göre fork'layıp revize etmek** — UI'ını, backend'ini ve entegre edilmesi gereken kısımlarını sistemimize uyarlamak.
- Ayrıca **Sprint 6 Reviewer** agent'ı için bir code-intelligence referansı olabilir (tüm dosyaları okumak yerine impact analizi).

---

## 5. İlke: Önce Odak

Asıl risk mimari değil, **scope creep / odak kaybı** — özellikle en riskli sprint olan S4'ün (Docker self-fix) ortasındayız.

1. **Şimdi:** S4'ü mevcut (mobil, greenfield) varsayımlarla bitir.
2. **Sonra:** Milestone A (TargetProfile).
3. **Daha sonra:** Milestone B (brownfield + gortex fork).

Çekirdek genel olduğu için bu genişlemeler ileride bizi cezalandırmaz; bugün aceleyle yapılırsa S4 riskini artırır.
