# Attio Custom Objects — REST API Reference

A working reference for reading and writing Attio **custom objects** via the v2 REST API.

> Source: Attio REST API docs (`docs.attio.com/rest-api`). Confirm exact filter
> syntax and max-limit values against the live docs before relying on edge cases.

## Core concept: custom objects are not a separate API

Attio's data model is **objects → records → attributes/values**. "Standard"
objects (People, Companies, Users, Workspaces, Deals) and **custom** objects are
the same kind of entity and use the **same generic endpoints**. You address any
object by its `object_id` (UUID) or its `api_slug` in the URL path. There is no
dedicated "custom objects" API — use the objects/records endpoints and pass your
custom object's slug.

- Base URL: `https://api.attio.com/v2`
- Auth: `Authorization: Bearer <token>` (API key or OAuth 2.0)
- Content type: `application/json`

## 1. List all objects (standard + custom)

```
GET /v2/objects
```

Returns **every object in the workspace — standard and custom together, in a
single response with no pagination** (no `limit`/`page`/`cursor` params on this
endpoint; you get the full list). Requires scope `object_configuration:read`.

Response:

```json
{
  "data": [
    {
      "id": {
        "workspace_id": "14beef7a-99f7-4534-a87e-70b564330a4c",
        "object_id": "97052eb9-e65e-443f-a297-f2d9a4a7f795"
      },
      "api_slug": "people",
      "singular_noun": "Person",
      "plural_noun": "People",
      "created_at": "2022-11-21T13:22:49.061281000Z"
    }
  ]
}
```

**There is no `is_standard` / `is_custom` flag.** To isolate custom objects,
filter out the known standard slugs (`people`, `companies`, `users`,
`workspaces`, `deals`); everything else is custom.

Related:
- `GET /v2/objects/{object}` — get one object by slug or UUID.
- `GET /v2/objects/{object}/attributes` — inspect an object's attribute schema.

## 2. Query records of a custom object

The primary read endpoint is a **POST**, not a GET:

```
POST /v2/objects/{object}/records/query
```

`{object}` = the object's `api_slug` or UUID. Same endpoint for standard and
custom objects — only the slug changes. Scopes: `record:read`,
`object_configuration:read`.

Request body (all fields optional):

```json
{
  "filter": { "name": "Acme" },
  "sorts": [{ "attribute": "name", "direction": "asc" }],
  "limit": 500,
  "offset": 0
}
```

- `filter` — Attio's structured filter syntax (`$eq`, `$contains`, `$gt`,
  nested `and`/`or`, etc.).
- `sorts` — array of `{ attribute, direction }`.
- `limit` / `offset` — pagination (see section 5).

## 3. Create / update / delete records

All bodies wrap attribute data in `data.values`.

### Create
```
POST /v2/objects/{object}/records
```
```json
{ "data": { "values": { "name": "Acme Inc.", "status": "active" } } }
```

### Update by ID (overwrite)
```
PATCH /v2/objects/{object}/records/{record_id}
```
Overwrites the supplied attributes. For **multiselect** attributes, PATCH
**replaces** the entire set.

### Upsert / "assert"
```
PUT /v2/objects/{object}/records?matching_attribute=<attribute_slug>
```
Finds a record where `matching_attribute` equals the supplied value and updates
it; creates a new record if none matches. With PUT, **multiselect values are
appended** rather than replaced. Scopes: `record_permission:read-write` +
`object_configuration:read`.

### Delete
```
DELETE /v2/objects/{object}/records/{record_id}
```
Returns `204` with no content.

## 4. What you get back per record

Records are **not** a flat key→value map. Each record is:

```json
{
  "data": {
    "id": {
      "workspace_id": "…",
      "object_id": "…",
      "record_id": "bf071e1f-6035-429d-b874-d83ea64ea13b"
    },
    "created_at": "2022-11-21T13:22:49.061281000Z",
    "web_url": "https://app.attio.com/your-workspace/…/record/…",
    "values": {
      "name": [
        {
          "active_from": "2022-11-21T13:22:49.061281000Z",
          "active_until": null,
          "created_by_actor": { "type": "api-token", "id": "…" },
          "attribute_type": "text",
          "value": "Acme Inc."
        }
      ]
    }
  }
}
```

Notes on `values`:

- Every attribute maps to an **array of value objects**, not a scalar, because
  Attio keeps a full **history** of each attribute.
- The **current** value is the one with `active_until: null`; superseded values
  carry an `active_until` timestamp. Multiselect attributes legitimately have
  multiple concurrent active entries.
- Each value carries `active_from`, `active_until`, `created_by_actor`, and an
  `attribute_type` (`text`, `number`, `date`, `select`, `record-reference`,
  `currency`, `location`, `email-address`, `phone-number`, etc.), plus
  type-specific value fields.
- Custom attributes appear as additional keys in `values`, in the same shape as
  standard ones.

## 5. Pagination — identical for standard and custom objects

Because custom and standard objects share the same record endpoints, they share
the same pagination behavior.

- **Offset/limit** is the primary model on `records/query`:
  - `limit` default **500**, `offset` default **0**.
  - Next page: repeat the call with `offset += limit`.
  - Max limit is not documented specifically for `records/query`; related
    list-entry endpoints document default **100 / max 1000**, so treat ~1000 as
    the practical ceiling.
- **Cursor-based** pagination is also available on some list endpoints: the
  response includes `pagination.next_cursor`, which you pass back as `cursor`.
- Nothing about pagination is custom-object-specific.

## Quick reference

| Action                      | Method & path                                                     |
|-----------------------------|-------------------------------------------------------------------|
| List all objects            | `GET /v2/objects`                                                 |
| Get one object              | `GET /v2/objects/{object}`                                        |
| List object attributes      | `GET /v2/objects/{object}/attributes`                            |
| Query records               | `POST /v2/objects/{object}/records/query`                        |
| Get a record                | `GET /v2/objects/{object}/records/{record_id}`                   |
| Create a record             | `POST /v2/objects/{object}/records`                              |
| Update a record (overwrite) | `PATCH /v2/objects/{object}/records/{record_id}`                |
| Upsert (assert) a record    | `PUT /v2/objects/{object}/records?matching_attribute=<slug>`     |
| Delete a record             | `DELETE /v2/objects/{object}/records/{record_id}`               |

`{object}` is always the object's `api_slug` or UUID; custom objects use their
own custom slug.
