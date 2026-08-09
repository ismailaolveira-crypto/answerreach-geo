import { RegisterForm } from "./register-form";
import { RegisterLightTrails, RegisterVisual } from "./register-visual";

export default async function RegisterPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ error?: string }> }>) {
  const params = await searchParams;
  return (
    <main className="cq-register-shell">
      <RegisterLightTrails />
      <RegisterVisual />
      <section className="cq-register-panel-wrap">
        <RegisterForm initialError={params.error} />
      </section>
    </main>
  );
}
