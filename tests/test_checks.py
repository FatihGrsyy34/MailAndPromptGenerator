from engine.checks.slop import banned_phrase_list, check_banned, check_etiquette, check_format, check_mail, check_rhythm
from engine.checks.tr_spelling import check_spelling_tr
from engine.text import sentences, tr_lower

GOOD_TR = """Merhaba Ahmet Bey,

Perşembe günkü demoyu 14.00'ten 16.00'ya almamız gerekiyor. Test ortamındaki güncelleme sabah bitmeyecek ve yarım bir sürümü göstermek istemiyoruz.

Saat size uyuyorsa takvim davetini güncelliyorum. Uymuyorsa cuma sabahı da bizim için mümkün.

İyi çalışmalar,
Fatih Gürsoy"""

AI_TR = """Merhaba Ahmet Bey,

Umarım bu e-posta sizi iyi bulur. Bu e-postayı demo toplantımız hakkında bilgi vermek amacıyla yazıyorum. Toplantı kapsamında yapılacak sunum sadece ürünü değil, aynı zamanda vizyonumuzu da göstermektedir. Ayrıca süreç titizlikle yürütülmektedir. Ayrıca ekibimiz hazırdır.

Başka sorunuz olursa çekinmeyin.

Saygılarımla,
Fatih"""


def test_tr_lower_handles_dotted_i():
    assert tr_lower("İSTANBUL IŞIK") == "istanbul ışık"


def test_clean_mail_has_no_hard_issues():
    issues = check_mail("Demo saati", GOOD_TR, "tr") + check_spelling_tr(GOOD_TR, ["Cognera"])
    assert [i for i in issues if i.hard] == []


def test_ai_mail_is_caught():
    spans = " | ".join(i.span for i in check_banned(AI_TR, "tr"))
    assert "Umarım bu e-posta sizi iyi bulur" in spans
    assert "çekinmeyin" in spans.lower()
    assert "sadece ürünü değil, aynı zamanda" in spans
    assert "Bu e-postayı demo toplantımız hakkında bilgi vermek amacıyla yazıyorum" in spans
    kinds = {i.message for i in check_rhythm(AI_TR, "tr")}
    assert any("geçiş" in k for k in kinds)
    assert any("aynı kelimeyle" in k for k in kinds)


def test_banned_matches_suffixes_and_case():
    assert check_banned("Lütfen ÇEKİNMEYİNİZ.", "tr")
    assert check_banned("We should delve into this.", "en")
    assert check_banned("I Hope This Email Finds You Well", "en")


def test_soft_words_alone_do_not_trigger():
    issues = check_banned("Kapsamlı bir test planı hazırladık.", "tr")
    assert issues and not any(i.hard for i in issues)
    issues = check_banned("Kapsamlı ve yenilikçi bir plan.", "tr")
    assert all(i.hard for i in issues)


def test_format_checks():
    msgs = " ".join(i.message for i in check_format("Merhaba,\n\n**Önemli**: toplantı — yarın; saat 10.\n- madde\n😀"))
    for needle in ("uzun tire", "noktalı virgül", "markdown", "emoji", "madde"):
        assert needle in msgs


def test_etiquette_title_stacking():
    assert check_etiquette("Sayın Ahmet Bey,\n\nMerhaba", "tr")
    assert not check_etiquette("Sayın Ahmet Yılmaz,\n\nMerhaba", "tr")


def test_spelling_rules():
    text = "Merhaba Ayşe Hanım\n\nHerşey hazır, yarın müsaitmisiniz? Toplantı uygunmu? Diyorki 1,500 TL ve 20% indirim var. Cognerada Türkçe'de yazdık, Ahmet Beye ilettim."
    found = {i.suggestion for i in check_spelling_tr(text, ["Cognera"])}
    for expected in ("her şey", "müsait misiniz", "uygun mu", "diyor ki", "1.500", "Cognera'da", "Türkçe", "Bey'e"):
        assert any(expected in s for s in found), expected
    assert any("virgül" in i.message for i in check_spelling_tr(text))


def test_spelling_no_false_positives_on_correct_text():
    text = "Merhaba,\n\nBelki de yarın geliriz, çünkü dosyalar hâlâ hazır değil. Uygun mu? Geliyor musunuz? Adımı attım."
    assert [i for i in check_spelling_tr(text) if i.hard] == []


def test_sentences_skip_greeting_and_signature():
    s = sentences(GOOD_TR)
    assert not any(x.startswith("Merhaba") for x in s)
    assert not any("Fatih" in x for x in s)
    assert len(s) >= 3


def test_banned_list_for_prompt_is_plain_text():
    text = banned_phrase_list("tr", limit=40)
    assert "umarım bu e-posta sizi iyi bulur" in text
    assert "\\" not in text


def test_day_case_and_format_cleanup():
    from engine.mail.pipeline import _fix_day_case, _format_cleanup
    assert _fix_day_case("Eylül yerine sehven Ağustos verilerini. 14 Ekim Salı. Cuma uygunum.") == \
        "Eylül yerine sehven ağustos verilerini. 14 Ekim Salı. Cuma uygunum."
    assert _format_cleanup("çözüm; HubSpot — oldu **x**") == "çözüm, HubSpot, oldu x"


def test_outlook_own_text_strips_reply_chain():
    from engine.mail.outlook_import import own_text
    body = "Merhaba Elif Hanım,\r\n\r\nSalı uygun. [cid:image001.png@01DA]\r\n\r\nİyi çalışmalar,\r\nFatih\r\n\r\nKimden: Elif Demir <elif@x.com>\r\nGönderildi: Pazartesi\r\nEski mesaj"
    t = own_text(body)
    assert t.startswith("Merhaba Elif Hanım,") and "Salı uygun." in t
    assert "Kimden" not in t and "Eski mesaj" not in t and "cid:" not in t
