# HastleFam — Copy Pack v1

Status: ready for implementation.
Language: Russian.
Format: templates for all key user-facing interactions.
Rule: placeholders in `{braces}` are implementation variables, not literal text.

---

## 1. `/start`

### Primary version
```text
✅ HastleFam на связи.

Можно просто писать сообщением:
• `{amount} {merchant}`
• `{amount} {merchant} {currency}`
• `{amount} {merchant} #{category}`

Например:
• `149 supermarket`
• `49.90 netflix EUR`
• `120 taxi #transport`

Дальше я сам предложу нужные действия кнопками.
```

### If user is not linked
```text
⚠️ Я не вижу твой профиль в этом household.

Нужно привязать Telegram-аккаунт к пользователю HastleFam.
Если это твой бот — проверь привязку в базе.
```

---

## 2. `/help`

```text
🧾 Что я умею сейчас

Основное:
• просто записать трату или доход сообщением
• помочь поправить дату, категорию, валюту и курс
• показать, что запланировано
• дать статус по месяцу

Команды:
• `/month` — статус месяца
• `/upcoming` — ближайшие запланированные платежи
• `/add` — ручной ввод, если нужен явный формат
• `/help` — подсказка по возможностям

Формат свободного ввода:
• `{amount} {merchant}`
• `{amount} {merchant} {currency}`
• `{amount} {merchant} #{category}`
• `{amount} {merchant} {currency} #{category}`

Поддерживаемые валюты:
• RUB
• USD
• USDT
• EUR
```

---

## 3. Successful capture

### Minimal
```text
✅ Записал.
```

### Recommended default
```text
✅ Записал.
{amount} {currency} · {merchant}
```

### If category was parsed too
```text
✅ Записал.
{amount} {currency} · {merchant} · {category}
```

### Inline action buttons after capture
Button labels:
- `📅 Дата`
- `🏷 Категория`
- `🗓 Запланировать`
- `💱 Валюта / курс`
- `✏️ Изменить`
- `✅ Готово`

Rule:
- show only actions that are still relevant;
- if everything is already clear, show only the most likely actions plus `✅ Готово`.

---

## 4. Missing category flow

### Immediate nudge after saving
```text
🏷 Категория не заполнена.
Выбери её сейчас, чтобы отчёт не был кривым.
```

### Button row title
```text
Выбери категорию:
```

### If postponed
```text
⚠️ Ок, запись сохранил без категории.
Я ещё напомню, чтобы добить её позже.
```

---

## 5. Missing date flow

### Prompt
```text
📅 Нужна дата.
Это прошло сегодня или в другой день?
```

### Buttons
- `Сегодня`
- `Вчера`
- `Выбрать дату`

### After update
```text
✅ Дату обновил.
Теперь запись стоит на {date}.
```

---

## 6. Missing currency flow

### Prompt
```text
💱 Не вижу валюту.
Выбери валюту для этой записи.
```

### Buttons
- `RUB`
- `USD`
- `USDT`
- `EUR`

### After update
```text
✅ Валюту обновил.
Теперь это {amount} {currency}.
```

---

## 7. Exchange / rate flow

### Entry point
```text
💱 Добавим курс обмена для этой операции?
```

### Guided flow — step 1
```text
Сколько списалось в исходной валюте?
```

### Guided flow — step 2
```text
Сколько получилось в целевой валюте?
```

### Guided flow — step 3 if manual rate is needed
```text
Укажи курс, если хочешь зафиксировать его вручную.
Если не укажешь, я посчитаю его из сумм.
```

### Success
```text
✅ Обмен записал.
{from_amount} {from_currency} → {to_amount} {to_currency}
Курс: {rate}
```

### Missing rate attention
```text
⚠️ Для этой записи не хватает курса.
Без него общий свод по валютам будет неточным.
```

Rule:
- exchange must not look like extra income;
- copy must frame it as conversion, not earning.

---

## 8. Duplicate check flow

### Warning
```text
⚠️ Похоже на повтор.
Похожая запись уже была недавно.
Записать ещё раз?
```

### Buttons
- `Да, записать`
- `Нет, отмена`

### If confirmed
```text
✅ Записал ещё раз.
```

### If cancelled
```text
Ок, не сохраняю.
```

---

## 9. Low-confidence / partial parse flow

### Could not understand enough to save
```text
⚠️ Не смог нормально разобрать сообщение.
Попробуй короче: `{amount} {merchant}`
```

### Amount missing
```text
⚠️ Не вижу сумму.
Начни сообщение с числа.
```

### Merchant missing
```text
⚠️ Не вижу, что это за трата.
Добавь короткое название после суммы.
```

### Category symbol hint
```text
Подсказка: категорию можно сразу указать как `#{category}`.
```

---

## 10. Edit flow

### Entry
```text
✏️ Что нужно поменять?
```

### Buttons
- `📅 Дата`
- `🏷 Категория`
- `💱 Валюта / курс`
- `🗓 Запланировать`
- `Сумма`
- `Название`

### Generic success
```text
✅ Обновил запись.
```

---

## 11. Planned payment flow

### Create from existing transaction
```text
🗓 Сделать из этого запланированный платёж?
```

### Ask due date
```text
Когда он должен пройти?
```

### Ask owner
```text
За кем это закрепить?
```

### Ask category if missing
```text
Нужна категория, чтобы платёж нормально попал в отчёты.
```

### Success
```text
✅ Запланировал.
{amount} {currency} · {title}
Срок: {due_date}
```

### `/upcoming` empty state
```text
🗓 На ближайшие 7 дней ничего не запланировано.
```

### `/upcoming` normal state
```text
🗓 Ближайшие платежи

{planned_items}
```

Where each item is rendered like:
```text
• {date} · {title} · {amount} {currency}
```

---

## 12. `/month` — monthly review

### Recommended structure
```text
📊 Месяц на сейчас

💸 Потрачено:
{spend_block}

💰 Доход:
{income_block}

🗓 Запланировано до конца месяца:
{planned_block}

🏷 Топ-категории:
{categories_block}

⚠️ Требует внимания:
{attention_block}
```

### Rules for block rendering

#### `spend_block`
Use either:
```text
• {amount_1} {currency_1}
• {amount_2} {currency_2}
```

And if converted summary exists:
```text
Итого в {base_currency}: {base_total}
```

#### `income_block`
Same structure as spend block.

#### `planned_block`
```text
• {date} · {title} · {amount} {currency}
```
If empty:
```text
• Ничего не запланировано
```

#### `categories_block`
```text
• {category}: {amount} {currency_or_base}
```

#### `attention_block`
Only show if relevant.
Possible lines:
```text
• {uncategorized_count} записей без категории
• {missing_rate_count} записей без курса
• {planned_due_count} платежей скоро к оплате
```
If nothing needs action:
```text
• Всё чисто
```

### Hard rules for `/month`
- no duplicate title lines;
- no repeated “month” wording;
- one-screen target;
- visually structured with emoji;
- no raw recurring jargon;
- planned payments, not recurring-first framing.

---

## 13. Daily status update — 10:00 MSK

### Main version
```text
🔔 Статус на сегодня

💸 Потрачено с начала месяца:
{spend_block}

💰 Доход с начала месяца:
{income_block}

🗓 Скоро к оплате:
{planned_soon_block}

⚠️ Добить:
{attention_block}
```

### If very little happened
```text
🔔 Статус на сегодня

Пока без сюрпризов.

💸 Потрачено с начала месяца:
{spend_block}

🗓 Скоро к оплате:
{planned_soon_block}
```

### Possible attention lines
```text
• {uncategorized_count} записей без категории
• {missing_rate_count} записей без курса
• {planned_today_count} платежей на сегодня
```

Rule:
- this is a short assistant nudge, not a report wall.

---

## 14. Reminder for uncategorized entries

```text
⚠️ Есть записи без категории.
Давай добьём их сейчас, чтобы сводка не плыла.
```

Buttons:
- `Выбрать категории`
- `Позже`

---

## 15. Reminder for missing exchange rate

```text
⚠️ Есть записи без курса обмена.
Лучше заполнить их сейчас, иначе общий свод будет неточным.
```

Buttons:
- `Заполнить курс`
- `Позже`

---

## 16. Empty states

### No month data
```text
📊 За этот месяц пока пусто.
Можно просто начать с первой записи сообщением.
```

### No categories yet
```text
🏷 Пока нет категорий в сводке.
Когда записи будут размечены, здесь появится структура трат.
```

### No income yet
```text
💰 Доходов за этот месяц пока нет.
```

---

## 17. Admin / technical failures that still need human wording

### Generic failure
```text
⚠️ Сейчас не получилось обработать запрос.
Попробуй ещё раз чуть позже.
```

### Bot alive but profile broken
```text
⚠️ Бот на связи, но я не могу сохранить запись для этого пользователя.
Нужно проверить привязку аккаунта.
```

### Command unavailable / not implemented
```text
⚠️ Эта команда пока не готова.
```

---

## 18. Copy rules for implementation

- do not invent new tone in code;
- do not swap “planned payments” back to “recurring” in user copy unless the screen is explicitly about recurrence setup;
- always show currency next to amount;
- never silently skip a user action;
- if something important is missing, ask for it directly.
