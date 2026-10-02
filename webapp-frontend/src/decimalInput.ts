// Ввод дробных чисел (#224, п.7). `<input type="number">` на iOS в русской локали рисует цифровую
// клавиатуру с запятой, но поведение зависит от локали WebView: часть связок «клавиатура/локаль»
// отдаёт value === "" на «12,5» (поле будто пустое, значение молча теряется). Надёжно — текстовое
// поле с inputMode="decimal" и своя нормализация: запятая → точка, лишнее выбрасываем.

/** "12,5" → "12.5"; допускает цифры и ОДНУ точку (вторая и любые другие символы отбрасываются). */
export function sanitizeDecimalInput(raw: string): string {
  const dotted = raw.replace(/[,٫、。]/g, ".");
  let seenDot = false;
  let result = "";
  for (const char of dotted) {
    if (char >= "0" && char <= "9") {
      result += char;
    } else if (char === "." && !seenDot) {
      seenDot = true;
      result += char;
    }
  }
  return result;
}
