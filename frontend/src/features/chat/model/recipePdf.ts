import type { MealPlan } from "../../../shared/api/types";

/** Cook-basis lines shown in the recipe overlay and PDF (not pack/buy checks). */
export function recipeIngredientLines(plan: MealPlan): string[] {
  return plan.ingredients.map((ingredient) =>
    ingredient.amount == null
      ? `${ingredient.name} — Quantity unresolved`
      : `${ingredient.name} — ${ingredient.amount} ${ingredient.unit}`,
  );
}

function escapePdfText(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function wrapLine(text: string, max = 90): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return [""];
  const lines: string[] = [];
  let current = words[0];
  for (const word of words.slice(1)) {
    if (`${current} ${word}`.length <= max) current = `${current} ${word}`;
    else {
      lines.push(current);
      current = word;
    }
  }
  lines.push(current);
  return lines;
}

/** Minimal single-font PDF of the overlay recipe content (title, portions, ingredients, steps). */
export function downloadRecipePdf(plan: MealPlan): void {
  const steps = plan.instructions ?? [];
  const body: string[] = [
    plan.title,
    `${plan.portions} portions`,
    "",
    "Ingredients",
    ...recipeIngredientLines(plan),
    "",
    "Steps",
    ...(steps.length
      ? steps.map((step, index) => `${index + 1}. ${step}`)
      : ["No cooking steps."]),
  ];
  const contentLines = body.flatMap((line) => wrapLine(line));
  const content: string[] = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"];
  contentLines.forEach((line, index) => {
    if (index) content.push("T*");
    content.push(`(${escapePdfText(line)}) Tj`);
  });
  content.push("ET");
  const stream = content.join("\n");
  const objects = [
    "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
    "2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
    "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n",
    `4 0 obj<< /Length ${stream.length} >>stream\n${stream}\nendstream\nendobj\n`,
    "5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const object of objects) {
    offsets.push(pdf.length);
    pdf += object;
  }
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (let i = 1; i <= objects.length; i++) {
    pdf += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  const blob = new Blob([pdf], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${plan.title.replace(/[^\w-]+/g, "_").slice(0, 80) || "recipe"}.pdf`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Overlay opens only when the plan carries real cooking steps (no invented free-form steps). */
export function mealPlanHasCookingSteps(plan: MealPlan): boolean {
  return (plan.instructions?.length ?? 0) > 0;
}
