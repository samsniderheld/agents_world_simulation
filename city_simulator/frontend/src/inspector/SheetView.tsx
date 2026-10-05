import type { CharacterSheet } from '../api/types';
import './inspector.css';

const STAT_ORDER = ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'];

// A Dice & DM character sheet (agents/dm/sheet.py): the six stats with
// modifiers, then what the dice have done to them -- mood, conditions,
// money, goals, and how they feel about people.
// `feelings` false leaves relationships out (the character view lists them
// with the people they've met instead).
export function SheetView({ sheet, feelings: showFeelings = true }: { sheet: CharacterSheet; feelings?: boolean }) {
  const feelings = Object.entries(showFeelings ? sheet.relationships : {})
    .filter(([, v]) => Math.abs(v) >= 5)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  return (
    <div className="sheet">
      <div className="sheet-stats">
        {STAT_ORDER.map((s) => (
          <div key={s} className="sheet-stat" title={sheet.stat_names[s]}>
            <div className="sheet-stat-name">{s}</div>
            <div className="sheet-stat-score">{sheet.stats[s]}</div>
            <div className="sheet-stat-mod">
              {sheet.modifiers[s] >= 0 ? '+' : ''}
              {sheet.modifiers[s]}
            </div>
          </div>
        ))}
      </div>
      <div className="sheet-rows">
        <div>
          <b>Mood</b> {sheet.mood_text}
        </div>
        <div>
          <b>Conditions</b>{' '}
          {Object.keys(sheet.conditions).length
            ? Object.entries(sheet.conditions)
                .map(([c, n]) => `${c} (${n} more tick${n === 1 ? '' : 's'})`)
                .join(', ')
            : 'none'}
        </div>
        <div>
          <b>Money</b> {sheet.money} {sheet.currency}
        </div>
      </div>
      {sheet.goals.length > 0 && (
        <>
          <div className="sheet-heading">Goals</div>
          <ul className="sheet-list">
            {sheet.goals.map((g, i) => (
              <li key={i} className={`sheet-goal is-${g.status}`}>
                {g.text} <span className="sheet-dim">{g.status === 'active' ? `${g.progress}/3` : g.status}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {feelings.length > 0 && (
        <>
          <div className="sheet-heading">Feelings</div>
          <ul className="sheet-list">
            {feelings.map(([name, v]) => (
              <li key={name}>
                {sheet.attitudes[name]} toward {name} <span className="sheet-dim">({v > 0 ? '+' : ''}{v})</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {!sheet.goals.length && !feelings.length && (
        <div className="sheet-dim">
          {showFeelings ? 'Goals and feelings appear' : 'Goals appear'} once a run with dice &amp; DM on has involved them.
        </div>
      )}
    </div>
  );
}
