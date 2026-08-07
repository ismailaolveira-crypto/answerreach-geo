import Link from "next/link";
import { LoginShowcaseCarousel } from "@/app/login/login-showcase-carousel";

export default async function RegisterPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ error?: string }> }>) {
  const params = await searchParams;
  return (
    <main className="cq-auth-page">
      <section className="cq-auth-intro">
        <div className="cq-auth-grain" aria-hidden="true" />
        <div className="cq-auth-carousel-stage"><LoginShowcaseCarousel /></div>
      </section>
      <section className="cq-auth-panel-wrap">
        <div className="cq-auth-card">
          <div className="cq-auth-card-heading">
            <div className="cq-auth-panel-brand"><i aria-hidden="true"><b /><b /><b /><b /></i><span>春秋元泉</span></div>
            <h2>创建工作区</h2>
            <p>创建后，你的品牌、问题与观测证据将只归属于这个账号。</p>
          </div>
          {params.error === "exists" ? <div className="cq-login-notice" role="status">该邮箱已注册，请直接登录。</div> : null}
          {params.error === "invalid" ? <div className="cq-login-notice" role="status">请检查填写内容后重试。</div> : null}
          <form action="/api/session/register" method="post" className="cq-login-form">
            <div><label htmlFor="register-name">姓名</label><input id="register-name" name="name" autoComplete="name" required /></div>
            <div><label htmlFor="register-email">邮箱</label><input id="register-email" name="email" type="email" autoComplete="email" placeholder="name@company.com" required /></div>
            <div><label htmlFor="register-company">公司名称</label><input id="register-company" name="company_name" autoComplete="organization" required /></div>
            <div><label htmlFor="register-brand">品牌名称</label><input id="register-brand" name="brand_name" required /></div>
            <div><label htmlFor="register-website">官网（可选）</label><input id="register-website" name="website_url" type="url" placeholder="https://" /></div>
            <div><label htmlFor="register-password">密码</label><input id="register-password" name="password" type="password" autoComplete="new-password" minLength={8} required /></div>
            <button className="cq-primary" type="submit"><span>创建并进入工作台</span><b aria-hidden="true">↗</b></button>
          </form>
          <div className="cq-demo-form"><Link href="/login">已有账号？登录 <span>↗</span></Link></div>
        </div>
      </section>
    </main>
  );
}
