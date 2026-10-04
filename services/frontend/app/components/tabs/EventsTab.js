"use client";

import { STRINGS } from "../../lib";
import { SearchBar, Toolbar } from "../controls";
import { EventsTable } from "../shared";

export default function EventsTab({ events, query, onQueryChange, error, loading, refresh }) {
  // Arama backend'de (?q=).
  return (
    <div className="panel">
      <Toolbar label={STRINGS.latestEvents} onRefresh={refresh} count={events?.length} />
      <SearchBar value={query} onChange={onQueryChange} />
      {error && <div className="error-banner">{error}</div>}
      <EventsTable events={events} loading={loading} />
    </div>
  );
}
