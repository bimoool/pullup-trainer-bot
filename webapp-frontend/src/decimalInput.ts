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
  // «.» / «,» первым символом → «0.»: одиночный разделитель не должен выглядеть как число (#224 review).
  return result.startsWith(".") ? `0${result}` : result;
}

/** Полное неотрицательное число для отправки: «12», «12.5», «12.» — да; «» и одиночный «.» — нет. */
export function isCompleteDecimal(raw: string): boolean {
  return /^\d+(\.\d*)?$/.test(raw.trim());
}
