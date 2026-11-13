"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, FileText, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
type Project = { id: string; name: string; description: string };
type Document = {
  id: string;
  title: string;
  content: string;
  source: string;
  version: number;
  approved: boolean;
};
export function ProjectContext({
  project,
  onMessage,
}: {
  project: Project;
  onMessage: (message: string) => void;
}) {
  const qc = useQueryClient(),
    [name, setName] = useState(project.name),
    [description, setDescription] = useState(project.description),
    [content, setContent] = useState(""),
    [source, setSource] = useState("workspace user"),
    [approved, setApproved] = useState(true),
    [busy, setBusy] = useState(false);
  const documents = useQuery({
    queryKey: ["knowledge", project.id],
    queryFn: () => api<Document[]>(`projects/${project.id}/knowledge`),
  });
  async function save(work: () => Promise<unknown>, message: string) {
    setBusy(true);
    try {
      await work();
      await qc.invalidateQueries();
      onMessage(message);
    } catch (e) {
      onMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel context-panel">
      <div className="panel-heading">
        <div>
          <h2>Project context</h2>
          <p className="muted">
            Versioned requirements with source provenance. Approved decisions
            take precedence.
          </p>
        </div>
        <FileText size={20} />
      </div>
      <div className="context-grid">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save(
              () =>
                api(`projects/${project.id}`, "PATCH", { name, description }),
              "Project details saved",
            );
          }}
        >
          <label htmlFor="edit-name">Project name</label>
          <input
            id="edit-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            minLength={1}
            maxLength={200}
            required
          />
          <label htmlFor="edit-description">Description</label>
          <textarea
            id="edit-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={10000}
          />
          <Button type="submit" variant="outline" disabled={busy}>
            <Save size={14} />
            Save project details
          </Button>
        </form>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save(async () => {
              await api(`projects/${project.id}/knowledge`, "POST", {
                title: "Requirements",
                content,
                source,
                approved,
              });
              setContent("");
            }, "New requirements version saved");
          }}
        >
          <label htmlFor="requirements">Requirements and source notes</label>
          <textarea
            id="requirements"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={30000}
            minLength={1}
            required
            placeholder="Paste requirements, approved decisions, or source material. Agents cannot overwrite these records."
          />
          <label htmlFor="source">Source</label>
          <input
            id="source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            required
            maxLength={1000}
          />
          <label className="check-label">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
            Mark as an approved project decision
          </label>
          <label className="file-input">
            <Upload size={14} />
            Import text document
            <input
              type="file"
              accept=".txt,.md,.json,text/plain,text/markdown,application/json"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                if (file.size > 30000) {
                  onMessage("Text documents must be at most 30 KB.");
                  return;
                }
                setContent(await file.text());
                setSource(file.name);
              }}
            />
          </label>
          <Button type="submit" disabled={busy || !content.trim()}>
            <Save size={14} />
            Save requirements version
          </Button>
        </form>
      </div>
      <div className="knowledge-history">
        <h3>Context history</h3>
        {documents.error && (
          <p className="error" role="alert">
            {(documents.error as Error).message}
          </p>
        )}
        {!documents.data?.length ? (
          <p className="muted">
            No context saved yet. Add requirements to give agents a reliable
            project brief.
          </p>
        ) : (
          documents.data.map((d) => (
            <details key={d.id}>
              <summary>
                {d.title} · v{d.version}
                <span className="status">
                  {d.approved ? "Approved" : "Suggestion"}
                </span>
              </summary>
              <p className="muted">Source: {d.source}</p>
              <pre>{d.content}</pre>
            </details>
          ))
        )}
      </div>
    </section>
  );
}
