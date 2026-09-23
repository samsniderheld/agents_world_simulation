// A two-step "Generate Character" modal: pick optional constraints,
// preview a draft (nothing persisted yet), edit any field, then Save
// actually creates it -- Regenerate re-runs the preview with the same
// constraints, Discard closes without saving anything.
import { useState } from 'react';
import { history } from '../api/client';
import type { Character, Place } from '../api/types';
import './newAgentModal.css';

interface Constraints {
  placeId: string;
  occupation: string;
  sex: string;
}

export function NewAgentModal({
  places,
  onCreated,
  onClose,
}: {
  places: Place[];
  onCreated: (character: Character) => void;
  onClose: () => void;
}) {
  const [constraints, setConstraints] = useState<Constraints>({ placeId: '', occupation: '', sex: '' });
  const [draft, setDraft] = useState<Character | null>(null);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [age, setAge] = useState('');
  const [occupation, setOccupation] = useState('');
  const [quirk, setQuirk] = useState('');
  const [bio, setBio] = useState('');

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const res = await history.previewCharacter({
        placeId: constraints.placeId || undefined,
        occupation: constraints.occupation.trim() || undefined,
        sex: constraints.sex || undefined,
      });
      const c = res.character;
      setDraft(c);
      setName(c.name ?? '');
      setAge(c.age != null ? String(c.age) : '');
      setOccupation(c.occupation ?? '');
      setQuirk(c.quirk ?? '');
      setBio(c.bio ?? '');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const edited: Character = {
        ...draft,
        name: name.trim() || draft.name,
        age: age.trim() ? Number(age) : draft.age,
        occupation: occupation.trim(),
        quirk: quirk.trim(),
        bio: bio.trim(),
      };
      const res = await history.createCharacter(edited);
      onCreated(res.character);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Generate Character</h3>
          <button className="modal-close" title="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        {!draft ? (
          <>
            <div className="modal-body">
              <label className="modal-field">
                <span>Ground this resident at</span>
                <select value={constraints.placeId} onChange={(e) => setConstraints((c) => ({ ...c, placeId: e.target.value }))}>
                  <option value="">Random</option>
                  {places.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.place_type})
                    </option>
                  ))}
                </select>
              </label>
              <div className="modal-field-row">
                <label className="modal-field">
                  <span>Occupation (optional)</span>
                  <input
                    type="text"
                    placeholder="any"
                    value={constraints.occupation}
                    onChange={(e) => setConstraints((c) => ({ ...c, occupation: e.target.value }))}
                  />
                </label>
                <label className="modal-field">
                  <span>Sex (optional)</span>
                  <select value={constraints.sex} onChange={(e) => setConstraints((c) => ({ ...c, sex: e.target.value }))}>
                    <option value="">Any</option>
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                  </select>
                </label>
              </div>
              <div className="modal-hint">
                These only shape the LLM-written draft -- the no-LLM fallback can honor occupation but has no way to act on sex.
              </div>
              {error && <div className="modal-error">{error}</div>}
            </div>
            <div className="modal-actions">
              <button className="node-run-btn" disabled={generating} onClick={generate}>
                {generating ? 'generating…' : '▶ Generate'}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="modal-sub">grounded at {draft.place_name || 'the city'}</div>
            <div className="modal-body">
              <div className="modal-field-row">
                <label className="modal-field">
                  <span>Name</span>
                  <input value={name} onChange={(e) => setName(e.target.value)} />
                </label>
                <label className="modal-field modal-field-narrow">
                  <span>Age</span>
                  <input type="number" min={1} value={age} onChange={(e) => setAge(e.target.value)} />
                </label>
              </div>
              <label className="modal-field">
                <span>Occupation</span>
                <input value={occupation} onChange={(e) => setOccupation(e.target.value)} />
              </label>
              <label className="modal-field">
                <span>Quirk</span>
                <input value={quirk} onChange={(e) => setQuirk(e.target.value)} />
              </label>
              <label className="modal-field">
                <span>Bio</span>
                <textarea rows={4} value={bio} onChange={(e) => setBio(e.target.value)} />
              </label>
              {(draft.history ?? []).length > 0 && (
                <>
                  <div className="modal-hint">Life history (not editable here -- Regenerate for a new one):</div>
                  <div className="modal-history">
                    {(draft.history ?? []).map((h, i) => (
                      <div className="modal-history-entry" key={i}>
                        <b>{h.year}</b> {h.gospel_text}
                      </div>
                    ))}
                  </div>
                </>
              )}
              {error && <div className="modal-error">{error}</div>}
            </div>
            <div className="modal-actions">
              <button className="node-run-btn" onClick={onClose}>
                Discard
              </button>
              <button className="node-run-btn" disabled={generating} onClick={generate}>
                {generating ? 'generating…' : '↻ Regenerate'}
              </button>
              <button className="node-run-btn" disabled={saving} onClick={save}>
                {saving ? 'saving…' : 'Save'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
