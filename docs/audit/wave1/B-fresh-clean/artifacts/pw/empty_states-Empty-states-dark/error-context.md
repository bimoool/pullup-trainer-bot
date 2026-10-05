# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: empty_states.spec.ts >> Empty states dark
- Location: audit/B-fresh-clean/empty_states.spec.ts:6:3

# Error details

```
Error: Channel closed
```

# Page snapshot

```yaml
- generic [ref=f4e4]:
  - paragraph [ref=f4e5]: Привет, Audit!
  - generic [ref=f4e6]:
    - generic [ref=f4e7]:
      - button "Назад" [ref=f4e8] [cursor=pointer]
      - button "В избранное" [ref=f4e12] [cursor=pointer]
    - heading "Пустая" [level=1] [ref=f4e18]
    - generic [ref=f4e19]:
      - paragraph [ref=f4e20]: Своя тренировка
      - paragraph [ref=f4e21]: Пока без упражнений
    - generic [ref=f4e22]:
      - button "Начать" [disabled] [ref=f4e23] [cursor=pointer]
      - button "Записать" [ref=f4e28] [cursor=pointer]
      - button "Добавить в план" [ref=f4e33] [cursor=pointer]
      - button "Изменить" [ref=f4e38] [cursor=pointer]
    - paragraph [ref=f4e43]: Упражнения
    - paragraph [ref=f4e44]: В тренировке пока нет упражнений
    - paragraph [ref=f4e45]: История
    - paragraph [ref=f4e46]: Вы ещё не выполняли эту тренировку
```