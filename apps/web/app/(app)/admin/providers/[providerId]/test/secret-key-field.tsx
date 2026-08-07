"use client";

import { useState } from "react";

export function SecretKeyField({ required, placeholder }: { required: boolean; placeholder: string }) {
  const [visible, setVisible] = useState(false);

  return <div className="sy-secret-field">
    <input
      id="provider-api-key"
      name="api_key"
      type={visible ? "text" : "password"}
      required={required}
      placeholder={placeholder}
      autoComplete="off"
      spellCheck={false}
    />
    <button type="button" aria-label={visible ? "隐藏 API Key" : "显示 API Key"} aria-pressed={visible} onClick={() => setVisible((value) => !value)}>
      {visible ? "◉" : "◎"}
    </button>
  </div>;
}
