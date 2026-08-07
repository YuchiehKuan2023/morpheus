import type { FC, KeyboardEvent } from 'react';
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/utils';
import type { SimulationUser } from '@/types';
import { ChevronDown, Search } from 'lucide-react';

interface Props {
  users: SimulationUser[];
  selected: Set<string>;
  disabled?: boolean;
  onToggle: (uid: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
}

function Avatar({ u, size = 'sm' }: { u: SimulationUser; size?: 'sm' | 'xs' }) {
  const cls = size === 'xs' ? 'user-select__avatar--xs' : '';
  return (
    <span className={cn('user-select__avatar', cls)}>
      {u.avatar_url ? (
        <img
          className="user-select__avatar-img"
          src={`/avatar/${u.avatar_url}`}
          alt=""
          draggable={false}
        />
      ) : (
        u.avatar_initials
      )}
    </span>
  );
}

const UserSelect: FC<Props> = ({
  users,
  selected,
  disabled,
  onToggle,
  onSelectAll,
  onClearSelection,
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  function closeDropdown() {
    setOpen(false);
    setQuery('');
  }

  const filtered = query.trim()
    ? users.filter(
        (u) =>
          u.display_name.toLowerCase().includes(query.toLowerCase()) ||
          u.user_id.toLowerCase().includes(query.toLowerCase())
      )
    : users;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        closeDropdown();
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  // Focus search when opening
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0);
    }
  }, [open]);

  function handleTriggerKey(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setOpen((o) => !o);
    }
    if (e.key === 'Escape') closeDropdown();
  }

  function handleOptionKey(e: KeyboardEvent, uid: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle(uid);
    }
    if (e.key === 'Escape') closeDropdown();
  }

  const selectedUsers = users.filter((u) => selected.has(u.user_id));

  return (
    <div className={cn('user-select', open && 'user-select--open')} ref={containerRef}>
      {/* ── Trigger ─────────────────────────────────────────────── */}
      <div
        className={cn('user-select__trigger', disabled && 'user-select__trigger--disabled')}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        tabIndex={disabled ? -1 : 0}
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={handleTriggerKey}
      >
        <div className="user-select__chips">
          {selectedUsers.length === 0 ? (
            <span className="user-select__placeholder">Select users</span>
          ) : (
            selectedUsers.map((u) => (
              <span key={u.user_id} className="user-select__chip">
                <Avatar u={u} size="xs" />
                <span className="user-select__chip-name">{u.display_name}</span>
                <button
                  className="user-select__chip-remove"
                  aria-label={`Remove ${u.display_name}`}
                  tabIndex={-1}
                  onPointerDown={(e) => {
                    // prevent trigger from getting the event
                    e.stopPropagation();
                    onToggle(u.user_id);
                  }}
                >
                  ✕
                </button>
              </span>
            ))
          )}
        </div>
        <span className={cn('user-select__chevron', open && 'user-select__chevron--open')}>
          <ChevronDown />
        </span>
      </div>

      {/* ── Dropdown ────────────────────────────────────────────── */}
      {open && (
        <div className="user-select__dropdown" role="listbox" aria-multiselectable="true">
          {/* Search */}
          <div className="user-select__search-wrap">
            <span className="user-select__search-icon">
              <Search />
            </span>
            <input
              ref={searchRef}
              className="user-select__search"
              type="text"
              placeholder="Search users…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && closeDropdown()}
            />
            {query && (
              <button
                className="user-select__search-clear"
                tabIndex={-1}
                onPointerDown={(e) => {
                  e.preventDefault();
                  setQuery('');
                  searchRef.current?.focus();
                }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Select all / clear */}
          <div className="user-select__bulk">
            <button
              className="user-select__bulk-btn"
              onPointerDown={(e) => {
                e.preventDefault();
                onSelectAll();
              }}
            >
              Select all
            </button>
            <span className="user-select__bulk-sep" />
            <button
              className="user-select__bulk-btn"
              onPointerDown={(e) => {
                e.preventDefault();
                onClearSelection();
              }}
            >
              Clear
            </button>
            <span className="user-select__bulk-count">
              {selected.size}/{users.length}
            </span>
          </div>

          {/* Options */}
          <ul className="user-select__list">
            {filtered.length === 0 ? (
              <li className="user-select__empty">No users match "{query}"</li>
            ) : (
              filtered.map((u) => {
                const isSelected = selected.has(u.user_id);
                return (
                  <li
                    key={u.user_id}
                    className={cn(
                      'user-select__option',
                      isSelected && 'user-select__option--selected'
                    )}
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={0}
                    onClick={() => onToggle(u.user_id)}
                    onKeyDown={(e) => handleOptionKey(e, u.user_id)}
                  >
                    <Avatar u={u} />
                    <span className="user-select__option-name">{u.display_name}</span>
                    <span className="user-select__option-email">{u.user_id.split('@')[0]}</span>
                    <span
                      className={cn('user-select__check', isSelected && 'user-select__check--on')}
                    >
                      {isSelected ? '✓' : ''}
                    </span>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
};

export default UserSelect;
