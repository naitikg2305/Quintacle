"use client";

import { useEffect, useState } from "react";
import { createTodo, listTodos, Todo, updateTodo } from "@/lib/api";

export default function TodosPage() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState("2");

  async function refresh() {
    setTodos(await listTodos());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function submit() {
    if (!title) return;
    await createTodo({ title, priority: Number(priority), due_date: dueDate || null });
    setTitle("");
    setDueDate("");
    await refresh();
  }

  async function complete(id: string) {
    await updateTodo(id, { done: true });
    await refresh();
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Todos — ranked by due date + priority</h1>

      <ul className="space-y-2">
        {todos.map((t) => (
          <li key={t.id} className="border rounded p-3 flex justify-between items-center text-sm">
            <span>
              <b>{t.title}</b> {t.due_date ? `— due ${t.due_date}` : "— no due date"}
              {t.start_time ? ` ${t.start_time}${t.end_time ? `–${t.end_time}` : ""}` : ""} (priority {t.priority})
            </span>
            <button onClick={() => complete(t.id)} className="text-xs underline">
              done
            </button>
          </li>
        ))}
        {todos.length === 0 && <p className="text-sm opacity-60">Nothing open.</p>}
      </ul>

      <div className="border rounded p-4 space-y-3">
        <h2 className="font-medium">Add a todo</h2>
        <input
          className="border rounded px-2 py-1 w-full text-sm"
          placeholder="title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <div className="flex gap-3">
          <input
            type="date"
            className="border rounded px-2 py-1 text-sm"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
          <select className="border rounded px-2 py-1 text-sm" value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="1">low</option>
            <option value="2">medium</option>
            <option value="3">high</option>
            <option value="4">urgent</option>
          </select>
        </div>
        <button onClick={submit} className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm">
          Add
        </button>
      </div>
    </div>
  );
}
