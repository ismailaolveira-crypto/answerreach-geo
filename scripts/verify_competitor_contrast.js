async (page) => {
  await page.locator("details").evaluateAll((nodes) => {
    for (const node of nodes) node.open = true;
  });
  const report = await page.evaluate(() => {
    const parseColor = (value) => {
      const match = value.match(/rgba?\((\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)(?:\D+(\d+(?:\.\d+)?))?\)/);
      if (!match) return [0, 0, 0, 0];
      return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] == null ? 1 : Number(match[4])];
    };
    const composite = (foreground, background) => {
      const alpha = foreground[3] + background[3] * (1 - foreground[3]);
      if (alpha === 0) return [255, 255, 255, 1];
      return [
        (foreground[0] * foreground[3] + background[0] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[1] * foreground[3] + background[1] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[2] * foreground[3] + background[2] * background[3] * (1 - foreground[3])) / alpha,
        alpha,
      ];
    };
    const backgroundFor = (element) => {
      const layers = [];
      for (let node = element; node; node = node.parentElement) {
        layers.push(parseColor(getComputedStyle(node).backgroundColor));
      }
      return layers.reverse().reduce(
        (background, foreground) => composite(foreground, background),
        [255, 255, 255, 1],
      );
    };
    const luminance = (rgb) => {
      const channels = rgb.slice(0, 3).map((value) => {
        const normalized = value / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const ratioFor = (foreground, background) => {
      const resolvedForeground = composite(foreground, background);
      const lighter = Math.max(luminance(resolvedForeground), luminance(background));
      const darker = Math.min(luminance(resolvedForeground), luminance(background));
      return (lighter + 0.05) / (darker + 0.05);
    };

    const samples = [];
    for (const element of document.querySelectorAll("body *")) {
      const text = [...element.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent?.replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join(" ");
      if (!text || element.closest('[aria-hidden="true"]')) continue;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      if (
        rect.width <= 0 || rect.height <= 0 || style.display === "none"
        || style.visibility === "hidden" || Number(style.opacity) === 0
      ) continue;
      const foreground = parseColor(style.color);
      const background = backgroundFor(element);
      const fontSize = Number.parseFloat(style.fontSize);
      const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
      const large = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
      const threshold = large ? 3 : 4.5;
      const ratio = ratioFor(foreground, background);
      samples.push({
        text: text.slice(0, 160),
        tag: element.tagName.toLowerCase(),
        font_size_px: Number(fontSize.toFixed(2)),
        font_weight: fontWeight,
        ratio: Number(ratio.toFixed(2)),
        threshold,
        pass: ratio + 0.001 >= threshold,
      });
    }
    const failures = samples.filter((sample) => !sample.pass);
    return {
      standard: "WCAG 2.2 AA",
      viewport: { width: innerWidth, height: innerHeight },
      sample_count: samples.length,
      pass_count: samples.length - failures.length,
      failure_count: failures.length,
      minimum_ratio: samples.length
        ? Number(Math.min(...samples.map((sample) => sample.ratio)).toFixed(2))
        : null,
      failures,
    };
  });
  return JSON.stringify(report);
}
