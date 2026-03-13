# HastleFam — Copy System v1

Status: approved baseline for the next product iteration.
Owner of copy: ChatGPT.
Purpose: define a single user-facing language system so the bot does not drift back into old wording or old product logic.

---

## 1. Product truth this copy must reflect

HastleFam is a Telegram-first money copilot for two.

Current product contract:
- free text is the default input;
- commands stay as secondary utilities;
- inline actions appear after capture;
- planned payments matter more than recurring in the current MVP;
- daily status update is a core habit loop;
- multi-currency is real MVP scope: RUB, USD, USDT, EUR;
- exchange is a manual guided flow for now;
- trust and correction matter more than “magic”.

This copy system must NOT reflect the old contract:
- not “no menus, no forms” as a rigid promise;
- not default-USD worldview;
- not recurring-first mental model;
- not silent duplicate skip;
- not technical error messages.

---

## 2. Voice

Base tone:
- calm;
- direct;
- useful;
- not corporate;
- not cute;
- not cold dashboard sludge.

Chosen style:
- “деловой, но дружелюбный” in Russian product tone;
- visually clear, with moderate emoji;
- no clowning;
- no hype;
- no fake intelligence.

The bot should feel like:
- a reliable assistant;
- not a fintech ad;
- not a playful mascot;
- not a stern accountant.

---

## 3. Writing rules

### Always do
- lead with the result;
- keep messages short;
- use 1 idea per line where useful;
- use emoji for structure, not decoration;
- tell the user what happens next;
- when something is missing, ask for the missing thing directly;
- when a choice is needed, make the choice explicit.

### Never do
- do not sound technical unless the issue is genuinely technical;
- do not say “confidence threshold”, “parse_status”, “dedup”, “enum”, “seed users table” to end users;
- do not silently discard user intent;
- do not imply automation that does not exist;
- do not pretend exchange rates are fetched automatically if they are not;
- do not overload one message with too many metrics.

---

## 4. Emoji system

Use emoji only for visual grouping.

Approved core emoji:
- ✅ success / done
- ✏️ edit / correction
- 📅 date
- 🏷 category
- 🗓 planned payment
- 💱 currency / exchange / rate
- 📊 summary / month
- 🔔 reminder / status / attention
- 💸 spend
- 💰 income
- ⚠️ attention needed
- 🧾 records / entries

Rules:
- max 1 emoji per line in normal messages;
- max 6 emoji in a long summary;
- no random emotional emoji;
- no emoji chains.

---

## 5. Formatting rules

### For short operational messages
Structure:
1. result line
2. optional detail line
3. action cue or buttons

### For summaries
Structure:
1. title line
2. grouped blocks
3. one “needs attention” block only if relevant

### For prompts
Structure:
1. state what is missing
2. ask for it simply
3. offer buttons if possible

---

## 6. Interaction-specific tone

### Success
- short;
- confirming;
- no celebration spam.

Example shape:
- “✅ Записал.”
- “✅ Готово.”
- “✅ Сохранил трату.”

### Clarification needed
- calm;
- precise;
- one missing field at a time if possible.

Example shape:
- “Нужна дата.”
- “Не вижу валюту.”
- “Нужна категория.”

### Warnings
- no panic;
- no blame;
- user-first wording.

Example shape:
- “⚠️ Похоже на повтор.”
- “⚠️ Не хватает курса обмена.”

### Daily nudges
- light assistant energy;
- concise;
- not preachy;
- should feel useful even when there is little to report.

---

## 7. Command language rules

Commands are utilities, not the main UX.

Commands may stay visible in help, but copy should always reinforce:
- the user can just type naturally;
- commands are there when needed.

Approved command framing:
- “Можно просто написать сообщением.”
- “Команды — если нужен быстрый доступ.”

Forbidden framing:
- “Use /add if plain text does not trigger” as the main instruction;
- “No menus, no forms” as a product slogan.

---

## 8. Category input rule

Category should be parsable from an explicit symbol in free text.

Recommended syntax for MVP:
- `#category`

Reason:
- visible;
- fast to type;
- easy to parse;
- familiar mental model.

Examples as template syntax only:
- `{amount} {merchant} #{category}`
- `{amount} {merchant} {currency} #{category}`

If category is missing:
- save the record if core fields are sufficient;
- immediately ask to fill category with buttons or quick reply;
- do not bury the issue.

---

## 9. Duplicate handling rule

Never silently skip a likely duplicate.

Correct user-facing pattern:
1. warn that the new message looks similar to a recent record;
2. ask whether to save it again;
3. user decides.

The bot must not behave as if it knows better than the user.

---

## 10. Multi-currency language rule

Supported currencies in MVP:
- RUB
- USD
- USDT
- EUR

Copy rules:
- always show currency near the amount;
- never hide currency when multiple currencies exist;
- if a base-currency total is shown, say clearly that it is converted;
- if a rate is missing, say so plainly.

---

## 11. Planned payments language rule

For current MVP, “planned payments” is the primary user-facing concept.

Use:
- “запланированный платёж”
- “запланировано на месяц”
- “скоро к оплате”

Avoid making recurring sound like the core interaction.
Recurring can exist later as an automation layer above planned payments.

---

## 12. Daily status update rule

Daily status update must:
- be useful at a glance;
- not feel like spam;
- point to what needs action;
- reinforce habit and trust.

It should answer:
- where the month stands;
- what is coming up;
- what is missing.

It should not try to be a full report.

---

## 13. What the bot must never say

Banned phrases / patterns:
- “Seed users table first.”
- “Looks like duplicate, skipped.”
- “Not confident enough to save.”
- “parse error”
- “dedup fingerprint”
- “enum value”
- “LLM unavailable”
- “No menus, no forms.”

Replace with human wording.

---

## 14. Decision hierarchy for copy

If there is tension between:
- sounding smart;
- sounding short;
- sounding safe;
- being operationally useful;

choose in this order:
1. operationally useful
2. clear
3. trustworthy
4. short
5. stylish

---

## 15. Shipping rule

No new user-facing text should be added in code unless it follows this document.
If the product contract changes, this document must be updated first or together with implementation.
