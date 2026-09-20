"""Hindi v1 translations for the highest-traffic screens.

Scope (v1): the screens a first-time/selling user actually reads — welcome,
SAFE SELL landing, deposit instructions, wallet card, verification prompts
and status notifications. Buttons/menus stay English; extend by adding keys.
Fallback for any missing key is English, always.
"""
from __future__ import annotations

HI: dict[str, str] = {
    # Keys are message-builder names from messages.py; {placeholders} are kept.
    "WELCOME": """नमस्ते! 🙏 SFOE P2P बॉट में स्वागत है

⚡ तुरंत क्रिप्टो बेचें (USDT/BTC/ETH)
💎 भरोसेमंद MARCO प्लेटफ़ॉर्म
🤑 SAFE गारंटीड INR पेमेंट
📢 चैनल पर अपना P2P ऐड पोस्ट करें

शुरू करने के लिए नीचे दिए बटन दबाएं 👇""",

    "SAFE_SELL_LANDING": """SFOE P2P बॉट में स्वागत है 💬

⚡ अपना क्रिप्टो सीधे INR में बेचें
🔒 हर पेमेंट ब्लॉकचेन पर verify होती है
💵 UPI/IMPS/CDM से तुरंत पेमेंट

आगे बढ़ने के लिए नीचे बटन दबाएं 👇""",

    "DEPOSIT_INSTRUCTIONS": """🤑 टोकन: {token}
🔗 नेटवर्क: {chain}

इस एड्रेस पर पेमेंट भेजें 👇:
<code>{address}</code>

⚠️ नोट: सही राशि या ज़्यादा भेजें। अतिरिक्त राशि आपके वॉलेट में जुड़ जाएगी।

पेमेंट के बाद ➡️ नीचे 'CHECK PAYMENT' दबाएं 👁""",

    "TX_HASH_PROMPT": """🔎 अपनी पेमेंट ब्लॉकचेन पर verify करें

अपने पेमेंट का transaction hash / TxID नीचे पेस्ट करें 👇
(BSC/ETH नेटवर्क पर 0x से शुरू होने वाला 66 अक्षरों का कोड, या TRON/Bitcoin पर 64 अक्षरों का TxID)

चाहें तो स्क्रीनशॉट भी भेज सकते हैं 📸

Approval से पहले पेमेंट ब्लॉकचेन पर check होती है — गलत या फर्ज़ी hash fail हो जाएगा.""",

    "VERIFYING_PAYMENT": """🔎 पेमेंट मिल गई!

हम आपका transaction ब्लॉकचेन पर verify कर रहे हैं। नेटवर्क confirm होने में कुछ मिनट लग सकते हैं ⏳

Confirm होते ही आपको मैसेज मिलेगा ✅""",

    "WALLET_CARD": """🧾 आपका वॉलेट बैलेंस

💰 ${balance}

👇 क्या करना चाहेंगे?""",

    "MY_STATS": """📊 @{username} की स्टैट्स {badge}

▪️ Member Since: {member_since}
▪️ P2P ऐड पोस्ट: {ads}
▪️ Safe Sell पूरे: {sells}
▪️ कुल Safe Sell Volume: ${volume}
▪️ Referrals: {referrals}

SAFE-SELL के लिए {bot_username} इस्तेमाल करें ⚡️""",

    "VERIFIED_USER": """✅ पेमेंट ब्लॉकचेन पर confirm हो गई!

{detail}

आपका transaction admin approval का इंतज़ार में है।
आमतौर पर कुछ ही मिनट लगते हैं ⚡""",

    "FAILED_USER": """⚠️ हम आपकी पेमेंट ब्लॉकचेन पर confirm नहीं कर पाए।

हमारी टीम जल्द ही review करेगी। देर होने पर support से संपर्क करें.""",

    "RECEIPT_USER": """💸 पेमेंट भेज दी गई! ✅

TX: {tx_id}
राशि: ${amount}
Payout Reference: <code>{reference}</code>

इस reference को अपने बैंक/UPI ऐप में check करें। कोई दिक्कत हो तो support संपर्क करें 🙏""",

    "CANCELLED_USER": """🚫 आपका request (TX {tx_id}) cancel कर दिया गया है।

अकाउंट unlock हो गया — जब चाहें नया request बना सकते हैं ✅""",
}


def tr(key: str, lang: str | None, default: str) -> str:
    """Return the Hindi variant for `key` when lang == 'hi', else `default`."""
    if lang == "hi":
        return HI.get(key, default)
    return default


def lang_of(user) -> str:
    value = getattr(user, "lang", None) or "en"
    return value if value in {"en", "hi"} else "en"
