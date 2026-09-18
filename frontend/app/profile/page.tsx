"use client";

import { useEffect, useState } from "react";
import { ActivityLevel, getProfile, getTargets, logBodyStat, Profile, Targets, updateProfile } from "@/lib/api";

const ACTIVITY_LEVELS: { value: ActivityLevel; label: string }[] = [
  { value: "sedentary", label: "Sedentary (little/no exercise)" },
  { value: "light", label: "Light (1-3 days/week)" },
  { value: "moderate", label: "Moderate (3-5 days/week)" },
  { value: "active", label: "Active (6-7 days/week)" },
  { value: "very_active", label: "Very active (physical job + training)" },
];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile>({
    height_cm: null,
    sex: null,
    birthdate: null,
    activity_level: "moderate",
    home_countries: [],
  });
  const [targets, setTargets] = useState<Targets | null>(null);
  const [weight, setWeight] = useState("");
  const [weightUnit, setWeightUnit] = useState("lb");
  const [status, setStatus] = useState<string | null>(null);

  async function refresh() {
    setProfile(await getProfile());
    setTargets(await getTargets());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function save() {
    setStatus("saving...");
    await updateProfile(profile);
    setStatus("saved");
    await refresh();
  }

  async function logWeight() {
    if (!weight) return;
    setStatus("logging weight...");
    await logBodyStat({ date: today(), metric: "weight", value: Number(weight), unit: weightUnit });
    setWeight("");
    setStatus("weight logged");
    await refresh();
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Profile</h1>
      <p className="text-sm opacity-60 -mt-4">
        Static stuff (height, sex, birthdate) here; weight is logged over time, not stored here — it feeds these targets
        from whatever you logged most recently.
      </p>

      <div className="border rounded p-4 space-y-3">
        <label className="block text-sm">
          Height (cm)
          <input
            type="number"
            className="block border rounded px-2 py-1 mt-1 w-40"
            value={profile.height_cm ?? ""}
            onChange={(e) => setProfile({ ...profile, height_cm: e.target.value ? Number(e.target.value) : null })}
          />
        </label>
        <label className="block text-sm">
          Sex (for the BMR formula)
          <select
            className="block border rounded px-2 py-1 mt-1 w-40"
            value={profile.sex ?? ""}
            onChange={(e) => setProfile({ ...profile, sex: (e.target.value || null) as Profile["sex"] })}
          >
            <option value="">select...</option>
            <option value="male">male</option>
            <option value="female">female</option>
          </select>
        </label>
        <label className="block text-sm">
          Birthdate
          <input
            type="date"
            className="block border rounded px-2 py-1 mt-1 w-40"
            value={profile.birthdate ?? ""}
            onChange={(e) => setProfile({ ...profile, birthdate: e.target.value || null })}
          />
        </label>
        <label className="block text-sm">
          Activity level
          <select
            className="block border rounded px-2 py-1 mt-1"
            value={profile.activity_level}
            onChange={(e) => setProfile({ ...profile, activity_level: e.target.value as ActivityLevel })}
          >
            {ACTIVITY_LEVELS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Home countries (comma-separated — photos taken here skip the country/state/city
          breakdown when dropped, just filed by date)
          <input
            type="text"
            placeholder="e.g. United States, India"
            className="block w-full border rounded px-2 py-1 mt-1"
            value={profile.home_countries.join(", ")}
            onChange={(e) =>
              setProfile({ ...profile, home_countries: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
            }
          />
        </label>
        <button onClick={save} className="bg-black text-white dark:bg-white dark:text-black rounded px-4 py-2 text-sm">
          Save profile
        </button>
      </div>

      <div className="border rounded p-4 space-y-3">
        <h2 className="font-medium">Log today&apos;s weight</h2>
        <div className="flex gap-2">
          <input
            type="number"
            className="border rounded px-2 py-1 text-sm w-28"
            placeholder="weight"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
          />
          <select className="border rounded px-2 py-1 text-sm" value={weightUnit} onChange={(e) => setWeightUnit(e.target.value)}>
            <option value="lb">lb</option>
            <option value="kg">kg</option>
          </select>
          <button onClick={logWeight} className="border rounded px-4 py-2 text-sm">
            Log weight
          </button>
        </div>
      </div>

      <div className="border rounded p-4">
        <h2 className="font-medium mb-2">Computed targets</h2>
        {targets && "error" in targets && <p className="text-sm opacity-60">{targets.error}</p>}
        {targets && !("error" in targets) && (
          <div className="grid grid-cols-4 gap-3 text-sm text-center">
            <div>
              <div className="opacity-60 text-xs">age</div>
              <div className="font-medium">{targets.age}</div>
            </div>
            <div>
              <div className="opacity-60 text-xs">BMR</div>
              <div className="font-medium">{targets.bmr} kcal</div>
            </div>
            <div>
              <div className="opacity-60 text-xs">TDEE (kcal target)</div>
              <div className="font-medium">{targets.tdee_kcal} kcal</div>
            </div>
            <div>
              <div className="opacity-60 text-xs">protein target</div>
              <div className="font-medium">{targets.protein_target_g} g</div>
            </div>
          </div>
        )}
      </div>

      {status && <p className="text-sm opacity-70">{status}</p>}
    </div>
  );
}
