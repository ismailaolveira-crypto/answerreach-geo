type BrandKey = "deepseek" | "doubao" | "qwen" | "kimi" | "glm" | "yuanbao" | "hunyuan";

const BRAND_ALIASES: Record<string, BrandKey> = {
  qianwen: "qwen",
};

const OFFICIAL_LOGOS: Record<BrandKey, { src: string; kind?: "wordmark" }> = {
  deepseek: { src: "/brand/deepseek.svg", kind: "wordmark" },
  doubao: { src: "/brand/doubao.png" },
  qwen: { src: "/brand/qwen.png" },
  kimi: { src: "/brand/kimi.ico" },
  glm: { src: "/brand/glm.svg", kind: "wordmark" },
  yuanbao: { src: "/brand/yuanbao.png" },
  hunyuan: { src: "/brand/yuanbao.png" },
};

export function BrandLogo({ brand, label, className = "" }: { brand: string; label: string; className?: string }) {
  const resolvedBrand = BRAND_ALIASES[brand] ?? (brand as BrandKey);
  const logo = OFFICIAL_LOGOS[resolvedBrand];

  if (!logo) return null;

  return <span className={`sy-brand-logo ${className}`} data-brand={resolvedBrand} data-kind={logo.kind ?? "symbol"}>
    <img alt={`${label} 官方标志`} src={logo.src} />
  </span>;
}
