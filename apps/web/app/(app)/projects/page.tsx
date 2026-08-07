import Link from "next/link";
import { getProjects, type Project } from "@/lib/api";
import type { Route } from "next";

export default async function ProjectsPage() {
  let projects: Project[] = [];
  try {
    projects = await getProjects();
  } catch {
    projects = [];
  }

  return (
    <div className="stack">
      <div className="topbar">
        <div>
          <div className="eyebrow">项目管理</div>
          <h1>GEO 项目</h1>
          <p className="subtle">每个项目对应一组目标问题、关键词、竞品和后续监测任务。</p>
        </div>
        <Link className="button" href="/projects/new">
          新建项目
        </Link>
      </div>

      <section className="panel">
        <div className="list">
          {projects.length === 0 ? (
            <p className="subtle">暂无项目。</p>
          ) : (
            projects.map((project) => (
              <div className="row" key={project.id}>
                <div>
                  <h3>{project.name}</h3>
                  <small>{project.description ?? "暂无描述"}</small>
                </div>
                <div className="row-actions">
                  <span className="tag">{project.status}</span>
                  <Link className="button secondary" href={`/projects/${project.id}/dashboard` as Route}>
                    驾驶舱
                  </Link>
                  <Link className="button secondary" href={`/projects/${project.id}`}>
                    详情
                  </Link>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
