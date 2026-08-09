import Link from "next/link";
import { LoginShowcaseCarousel } from "./login-showcase-carousel";

export default async function LoginPage({
  searchParams
}: Readonly<{ searchParams: Promise<{ expired?: string; error?: string }> }>) {
  const params = await searchParams;
  return (
    <main className="cq-auth-page">
      <section className="cq-auth-intro">
        <div className="cq-auth-grain" aria-hidden="true" />
        <div className="cq-auth-carousel-stage">
          <LoginShowcaseCarousel />
        </div>
      </section>
      <section className="cq-auth-panel-wrap">
        <div className="cq-auth-card">
          <div className="cq-auth-card-heading">
            <div className="cq-auth-panel-brand"><i aria-hidden="true"><b /><b /><b /><b /></i><span>春秋元泉</span></div>
            <h2>登录工作台</h2>
            <p>使用工作账号，继续你的 GEO 观测。</p>
          </div>

          {params.expired ? (
            <div className="cq-login-notice" role="status">登录状态已过期，请重新登录。</div>
          ) : null}

          {params.error === "invalid" ? (
            <div className="cq-login-notice" role="status">邮箱或密码不正确，请重试。</div>
          ) : null}

          {params.error === "unavailable" ? (
            <div className="cq-login-notice" role="status">账号服务暂时无法连接，请确认本地 API 已启动。</div>
          ) : null}

          <form action="/api/session/login" method="post" className="cq-login-form">
            <div>
              <label htmlFor="login-email">邮箱</label>
              <input id="login-email" name="email" type="email" placeholder="name@company.com" autoComplete="email" required />
            </div>
            <div>
              <label htmlFor="login-password">密码</label>
              <input id="login-password" name="password" type="password" placeholder="输入你的密码" autoComplete="current-password" required />
            </div>
            <button className="cq-primary" type="submit">
              <span>进入工作台</span><b aria-hidden="true">↗</b>
            </button>
          </form>

          <div className="cq-demo-form">
            <Link href="/register">没有账号？创建你的 GEO 工作区 <span>↗</span></Link>
          </div>
        </div>
        <p className="cq-auth-footnote">仅限授权成员访问 · 数据与操作均保留审计记录</p>
      </section>
    </main>
  );
}
