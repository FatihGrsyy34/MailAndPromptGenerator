# Mail & Prompt Generator

İş için mail atılırken maillerin LLM'lere sorulması ve düzenlenmesi için her defasında kaybedilen zamanın telafi edilmesi; LLM'lere prompt verilirken daha detaylı ve güzel promptların hızlıca alınması.

Windows'ta her yerden **Ctrl+Space** ile açılır: seçenekleri seçip birkaç kelime yazarsınız, Google Gemini ile insan eliyle yazılmış gibi, TDK kurallarına uygun iş maili ya da tam istediğinizi anlatan prompt hazırlanır ve bulunduğunuz yere yapıştırılır.

## Masaüstü uygulaması
- Başlatma: `PromptGenerator.cmd` dosyasına çift tıklayın (konsol penceresi açılmaz). Sağ alttaki tepside mor ikon çıkar.
- Herhangi bir uygulamada **Ctrl+Space**: pencere imlecin yanında açılır. Metin seçiliyse otomatik alınır (seçili bir maile yanıt yazmak için).
- Akış: `M` Mail / `P` Prompt → seçenekler (`1`-`8` ton/konu, ok tuşları) → `Ctrl+Enter` yaz → `Enter` yapıştır. `Esc` geri/kapat, `E` düzenle, `Shift+1/2/3` daha kısa/resmi/samimi, `Ctrl+R` yeniden.
- Kısayol başka bir uygulamada kullanılıyorsa sırayla `Ctrl+Shift+Space`, `Ctrl+Alt+Space` denenir; `config.toml` → `[hotkey]` ile değiştirilebilir.
- Tepsi menüsü: Aç, **Windows açılışında başlat** (işaretle/kaldır), Ayarlar klasörünü aç, Çıkış.
- Günlük: `user_data/app.log`. Son seçimler `user_data/ui_state.json` içinde hatırlanır.
- Gemini ücretsiz kademesinde model başına günlük istek kotası düşüktür (örn. 20); uygulama kotası dolan ya da yoğun olan modeli atlayıp `config.toml`'daki yedek modellere geçer. Yoğun kullanımda ücretli kademe önerilir.

## Kurulum
Sanal ortam proje içinde: `.venv` (`python -m venv .venv`, sonra `.venv\Scripts\python.exe -m pip install -e .[dev] pywebview comtypes`). `pg.cmd` onu kullanır.

```bash
pg setkey
```
```bash
pg models
```
`pg models` çıktısındaki adlarla `config.toml` → `[models]` bölümünü kontrol edin.

## Kullanım
```bash
pg mail "Ahmet Bey'e perşembe demosunu 16.00'ya aldığımızı yaz, sebep test ortamı" --tone kibar --to musteri --length kisa
```
```bash
pg mail "salı uygun, linki ben atarım" --reply-file gelen_mail.txt
```
```bash
pg prompt "satislar.xlsx'ten aylık bölge özeti çıkaran pandas scripti" --type kod --target chatgpt --detail detayli
```
Çıktıdan sonra düzeltme isteyebilirsiniz ("daha kısa", "daha resmi") ya da prompt varsayımlarını düzenleyebilirsiniz. `--trace` her adımı gösterir.

Seçenekler: tonlar `engine/data/tones.yaml`, prompt türleri/hedefler `engine/data/prompt_options.yaml`.

## Sabit şablonlar
Mail ekranında **Şablonlar** (`T` tuşu): PDD gönderimi/hatırlatma/revizyon, analiz sonrası paylaşım, demo kaydı, canlıya geçiş, canlı sonrası, UAT/analiz/PoC davetleri. Alanları doldurup **Doldur** (Gemini'siz, anında) ya da **Gemini ile uyarla** (notunuza göre sadece ilgili cümleleri değiştirir). Şablon metinleri: `engine/data/mail_templates.yaml` (gerçek maillerden; "taslak" etiketliler gerçek örnekle güncellenecek).

## Stil profili (mailleri sizin gibi yazması için)
- Profil: `user_data/style_profile.md` (elle düzenlenebilir; varsa her mailde kullanılır, hiçbir servise gönderilmeden hazırlandı).
- Klasik Outlook'tan gönderilmiş mailleri içe aktarma (yerel, şifresiz): `pg style import-outlook --count 60 --months 12` → `user_data/style_samples/outlook_sent.txt`. Klasik Outlook yalnızca açıldığında senkronlanır; güncel mailler için önce bir kez açın.
- `pg style build` örnekleri Gemini'ye göndererek otomatik profil çıkarır (onay ister; ücretsiz kademede Google içerikleri kullanabilir).

## Motor nasıl çalışıyor
**Mail:** taslak (ton kartı + alıcı + dil kuralları + stil profili + benzer gerçek mailler) → humanize/eleştiri (5 boyutlu puan, sadece sorunlu yerleri yeniden yazar) → otomatik kontroller (yasaklı kalıplar, em-dash, ritim, TDK) → yazım denetimi (metni yeniden yazarsa reddedilir) → son kontrol.

**Prompt:** analiz (amaç, aynen korunacak kısıtlar, bilinmeyenler) → gerekirse en fazla 3 soru → üretim (iş türü şablonu + hedef model formatı + detay bütçesi) → doğrulama (eksik kısıt / uydurulmuş gereksinim) → gerekirse 1 onarım.

Tüm promptlar `engine/prompts/*.md` altında; kod değiştirmeden düzenlenebilir. Yasaklı kalıplar: `engine/data/banned_tr.txt`, `banned_en.txt`.

## Kalite ölçümü
```bash
.venv\Scripts\python.exe evals\run_evals.py
```
Her prompt değişikliğinden sonra çalıştırın; puanlar bir önceki çalıştırmayla karşılaştırılır. Vakalar: `evals/mail_cases.jsonl`, `evals/prompt_cases.jsonl` (kendi gerçek senaryolarınızı ekleyin).

Birim testleri (API gerekmez):
```bash
.venv\Scripts\python.exe -m pytest -q
```
