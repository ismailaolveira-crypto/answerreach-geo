"use client";

import Link from "next/link";
import { type FormEvent, type KeyboardEvent, useMemo, useRef, useState } from "react";

type RegisterError = "exists" | "invalid" | "unavailable";

const errorMessages: Record<RegisterError, string> = {
  exists: "该邮箱已经注册。你可以直接登录，或换一个邮箱创建工作区。",
  invalid: "账号信息没有通过校验，请检查邮箱、官网地址和密码后重试。",
  unavailable: "账号服务暂时无法连接，请确认本地 API 已启动后重试。"
};

export function RegisterForm({ initialError }: Readonly<{ initialError?: string }>) {
  const formRef = useRef<HTMLFormElement>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [inlineError, setInlineError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [brandName, setBrandName] = useState("");

  const passwordScore = useMemo(() => {
    return [password.length >= 8, /[a-zA-Z]/.test(password), /\d/.test(password), /[^a-zA-Z\d]/.test(password)].filter(Boolean).length;
  }, [password]);

  const passwordLabel = passwordScore >= 4 ? "强" : passwordScore >= 3 ? "良好" : passwordScore >= 2 ? "可用" : "待完善";
  const workspaceLabel = brandName.trim() || companyName.trim() || "你的品牌工作区";
  const externalError = initialError && initialError in errorMessages ? errorMessages[initialError as RegisterError] : "";

  const validateAccountStep = () => {
    const form = formRef.current;
    if (!form) return false;

    for (const fieldName of ["name", "email", "password", "confirm_password"]) {
      const field = form.elements.namedItem(fieldName);
      if (field instanceof HTMLInputElement && !field.checkValidity()) {
        field.reportValidity();
        return false;
      }
    }

    if (password !== confirmPassword) {
      setInlineError("两次输入的密码不一致。");
      return false;
    }

    setInlineError("");
    return true;
  };

  const continueToWorkspace = () => {
    if (!validateAccountStep()) return;
    setStep(2);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (step === 1 && event.key === "Enter" && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      continueToWorkspace();
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    if (step === 1) {
      event.preventDefault();
      continueToWorkspace();
      return;
    }
    if (!validateAccountStep()) {
      event.preventDefault();
      setStep(1);
      return;
    }
    setSubmitting(true);
  };

  return (
    <div className={`cq-register-card is-step-${step}`}>
      <div className="cq-register-heading">
        <div className="cq-register-heading-copy">
          <div className="cq-register-brand"><i aria-hidden="true"><b /><b /><b /></i><span>春秋元泉</span></div>
          <h1>建立 GEO 观测空间</h1>
          <p>创建管理员身份，再定义企业与品牌边界。</p>
        </div>
      </div>

      <ol className="cq-register-steps" aria-label="创建工作区进度">
        <li aria-current={step === 1 ? "step" : undefined} className={step === 1 ? "is-active" : "is-done"}><span>{step === 1 ? "1" : "✓"}</span><div><b>管理员账号</b></div></li>
        <li aria-current={step === 2 ? "step" : undefined} className={step === 2 ? "is-active" : ""}><span>2</span><div><b>品牌工作区</b></div></li>
      </ol>

      {externalError ? <div className="cq-register-notice" role="status"><i aria-hidden="true">!</i><span>{externalError}</span></div> : null}
      {inlineError ? <div className="cq-register-notice" role="alert"><i aria-hidden="true">!</i><span>{inlineError}</span></div> : null}

      <form action="/api/session/register" method="post" className="cq-register-form" ref={formRef} onKeyDown={handleKeyDown} onSubmit={handleSubmit}>
        <fieldset className="cq-register-stage" hidden={step !== 1}>
          <legend className="cq-auth-sr-only">管理员账号</legend>
          <div className="cq-register-field">
            <label htmlFor="register-name">姓名</label>
            <input id="register-name" name="name" autoComplete="name" placeholder="输入管理员姓名" maxLength={255} required />
          </div>
          <div className="cq-register-field">
            <label htmlFor="register-email">工作邮箱</label>
            <input id="register-email" name="email" type="email" autoComplete="email" placeholder="name@company.com" required />
          </div>
          <div className="cq-register-field">
            <div className="cq-register-label-row"><label htmlFor="register-password">设置密码</label><span className={`is-score-${passwordScore}`}>{passwordLabel}</span></div>
            <div className="cq-register-password-control">
              <input id="register-password" name="password" type={showPassword ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={255} placeholder="至少 8 位字符" value={password} onChange={(event) => { setPassword(event.target.value); setInlineError(""); }} required />
              <button type="button" aria-label={showPassword ? "隐藏密码" : "显示密码"} aria-pressed={showPassword} onClick={() => setShowPassword((current) => !current)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.8 12s3.4-5 9.2-5 9.2 5 9.2 5-3.4 5-9.2 5-9.2-5-9.2-5Z" /><circle cx="12" cy="12" r="2.4" /></svg></button>
            </div>
            <div className="cq-register-strength" aria-hidden="true">{[1, 2, 3, 4].map((score) => <i className={passwordScore >= score ? "is-filled" : ""} key={score} />)}</div>
          </div>
          <div className="cq-register-field">
            <label htmlFor="register-confirm-password">确认密码</label>
            <div className="cq-register-password-control">
              <input id="register-confirm-password" name="confirm_password" type={showPassword ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={255} placeholder="再输入一次密码" value={confirmPassword} onChange={(event) => { setConfirmPassword(event.target.value); setInlineError(""); }} required />
              <button type="button" aria-label={showPassword ? "隐藏确认密码" : "显示确认密码"} aria-pressed={showPassword} onClick={() => setShowPassword((current) => !current)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.8 12s3.4-5 9.2-5 9.2 5 9.2 5-3.4 5-9.2 5-9.2-5-9.2-5Z" /><circle cx="12" cy="12" r="2.4" /></svg></button>
            </div>
          </div>
          <div className="cq-register-trust"><i aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 2.8 19 5.5v5.8c0 4.4-2.8 8.2-7 9.9-4.2-1.7-7-5.5-7-9.9V5.5L12 2.8Z" /><path d="m8.8 12 2.1 2.1 4.4-4.5" /></svg></i><span><b>本地优先的账号安全</b><small>服务端仅保存密码哈希，不保存明文密码。</small></span></div>
          <button className="cq-register-primary" type="button" onClick={continueToWorkspace}><span>继续设置工作区</span><b aria-hidden="true">→</b></button>
        </fieldset>

        <fieldset className="cq-register-stage" hidden={step !== 2}>
          <legend className="cq-auth-sr-only">品牌工作区</legend>
          <div className="cq-register-field">
            <label htmlFor="register-company">公司名称</label>
            <input id="register-company" name="company_name" autoComplete="organization" placeholder="例如：春秋元泉科技" maxLength={255} value={companyName} onChange={(event) => setCompanyName(event.target.value)} required />
          </div>
          <div className="cq-register-field">
            <label htmlFor="register-brand">品牌名称</label>
            <input id="register-brand" name="brand_name" placeholder="将用于 GEO 观测与竞品比较" maxLength={255} value={brandName} onChange={(event) => setBrandName(event.target.value)} required />
          </div>
          <div className="cq-register-field">
            <div className="cq-register-label-row"><label htmlFor="register-website">官方网站</label><span>可选</span></div>
            <input id="register-website" name="website_url" type="url" autoComplete="url" placeholder="https://www.example.com" maxLength={500} />
          </div>

          <div className="cq-register-preview" aria-live="polite">
            <div className="cq-register-preview-mark">{workspaceLabel.slice(0, 1).toUpperCase()}</div>
            <div><small>WORKSPACE PREVIEW</small><b>{workspaceLabel}</b><span>你将成为所有者 · 数据默认隔离</span></div>
            <i aria-hidden="true">◇</i>
          </div>

          <div className="cq-register-actions">
            <button className="cq-register-secondary" type="button" onClick={() => setStep(1)}>← 返回</button>
            <button className="cq-register-primary" type="submit" disabled={submitting}><span>{submitting ? "正在初始化..." : "创建并进入工作台"}</span><b aria-hidden="true">↗</b></button>
          </div>
        </fieldset>
      </form>

      <div className="cq-register-login-link"><span>已有账号？</span><Link href="/login">返回登录 <b aria-hidden="true">↗</b></Link></div>
    </div>
  );
}
