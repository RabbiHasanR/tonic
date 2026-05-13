# The Complete Guide to GraphQL Pagination

Pagination is how we break massive database lists into small, fast chunks for the user interface. In GraphQL, there are three main ways to handle this: **Offset-Based**, **Page-Based**, and **Cursor-Based (Relay)**.

---

## 1. Offset-Based Pagination

This is the raw, database-native way to paginate. You tell the server exactly how many items to **skip** (`offset`) and how many to **take** (`limit`).

### 💻 The Client Query (Frontend)

```graphql
query GetUsers {
  users(limit: 10, offset: 20) { # Skips the first 20, grabs the next 10
    id
    name
  }
}

```

### 📝 The GraphQL Schema

```graphql
type User {
  id: ID!
  name: String!
}

type Query {
  users(limit: Int!, offset: Int!): [User!]!
}

```

### ⚙️ The Backend Resolver

```javascript
const resolvers = {
  Query: {
    users: async (_, { limit, offset }) => {
      // Pass the arguments directly to your database
      return await db.query('SELECT * FROM users LIMIT $1 OFFSET $2', [limit, offset]);
    }
  }
};

```

### 🗄️ The Database SQL

```sql
SELECT * FROM users ORDER BY created_at DESC LIMIT 10 OFFSET 20;

```

**Verdict:** Super easy to write, but gets very slow on large datasets (the database has to count and discard all the skipped rows). Also suffers from "Data Drift"—items can duplicate if new data is added while the user is scrolling.

---

## 2. Page-Based Pagination

This is exactly the same as Offset pagination, but it uses user-friendly terminology (`page` and `perPage`). The frontend doesn't have to calculate offsets; the backend does the math.

### 💻 The Client Query (Frontend)

```graphql
query GetUsers {
  users(page: 3, perPage: 10) { # Give me the 3rd page, 10 items per page
    id
    name
  }
}

```

### 📝 The GraphQL Schema

```graphql
type Query {
  users(page: Int!, perPage: Int!): [User!]!
}

```

### ⚙️ The Backend Resolver (Where the math happens)

```javascript
const resolvers = {
  Query: {
    users: async (_, { page, perPage }) => {
      // The math: To get page 3 (10 per page), skip the first 20.
      const offset = (page - 1) * perPage; 
      const limit = perPage;

      return await db.query('SELECT * FROM users LIMIT $1 OFFSET $2', [limit, offset]);
    }
  }
};

```

### 🗄️ The Database SQL

```sql
-- The database sees the exact same query as Offset-based
SELECT * FROM users ORDER BY created_at DESC LIMIT 10 OFFSET 20;

```

**Verdict:** Great for traditional e-commerce or admin tables where users want to click page numbers at the bottom of the screen. However, it suffers from the exact same performance and data drift issues as Offset pagination.

---

## 3. Cursor-Based Pagination (The Relay Standard)

Instead of skipping rows by a number, you use a **Cursor** (a bookmark) and say: *"Give me 10 items starting exactly AFTER this bookmark."* Because of its performance, this is the industry gold standard for GraphQL.

### 💻 The Client Query (Frontend)

Notice how we must ask for `edges`, `node`, and `pageInfo`.

```graphql
query GetUsers {
  users(first: 10, after: "aWQ6MjA=") {
    edges {
      cursor # The bookmark for this specific item
      node {
        id
        name
      }
    }
    pageInfo {
      hasNextPage     # Tells our UI to show a "Load More" button (forward)
      hasPreviousPage # Tells our UI to show a "Load Previous" button (backward)
      startCursor     # Cursor of the FIRST item in this page (used for 'before')
      endCursor       # Cursor of the LAST item in this page (used for 'after')
    }
    totalCount # Optional: total rows that match (costs an extra COUNT query)
  }
}

```

### 📝 The GraphQL Schema

```graphql
# Full Relay-spec PageInfo — all four fields
type PageInfo {
  hasNextPage: Boolean!     # More items after endCursor?
  hasPreviousPage: Boolean! # More items before startCursor?
  startCursor: String       # Cursor of first edge (null if no edges)
  endCursor: String         # Cursor of last edge (null if no edges)
}

type User {
  id: ID!
  name: String!
}

# The Edge wraps the Node and holds its specific Cursor
type UserEdge {
  cursor: String!
  node: User!
}

# The Connection is the final wrapper
type UserConnection {
  edges: [UserEdge!]!
  pageInfo: PageInfo!
  totalCount: Int! # Common (non-spec) extension — handy for "Page 3 of 42" UIs
}

# Full Relay signature: forward AND backward pagination.
# `first`/`after` walks forward, `last`/`before` walks backward.
# All four are optional; the client picks a direction.
type Query {
  users(
    first: Int
    after: String
    last: Int
    before: String
  ): UserConnection!
}

```

### ⚙️ The Backend Resolver

> ⚠️ **Sort assumption:** the resolver below assumes `ORDER BY id ASC`. If you
> sort by any other column (or descending), the `WHERE id > $1` clause is wrong —
> see the tuple-comparison note at the end of this section.

```javascript
const resolvers = {
  Query: {
    users: async (_, { first, after }) => {
      let decodedId = 0;

      // 1. Decode the cursor if it exists.
      //    We encode JSON (not a plain string) so the cursor can later carry
      //    tuple data like { id: 20, name: "John" } without changing the format.
      if (after) {
         decodedId = JSON.parse(decodeBase64(after)).id;
      }

      // 2. Fetch from DB (We ask for 'first + 1' to see if a next page exists)
      const rows = await db.query(
        'SELECT * FROM users WHERE id > $1 ORDER BY id ASC LIMIT $2',
        [decodedId, first + 1]
      );

      // 3. Check if there is a next page, then remove that extra item
      const hasNextPage = rows.length > first;
      const nodesToReturn = hasNextPage ? rows.slice(0, -1) : rows;

      // 4. Format into Edges (cursor is opaque base64-of-JSON)
      const edges = nodesToReturn.map(row => ({
        cursor: encodeBase64(JSON.stringify({ id: row.id })),
        node: row
      }));

      // 5. Return the Relay structure with full PageInfo
      return {
        edges: edges,
        pageInfo: {
          hasNextPage: hasNextPage,
          hasPreviousPage: decodedId > 0, // we came from somewhere => there's a previous page
          startCursor: edges.length > 0 ? edges[0].cursor : null,
          endCursor:   edges.length > 0 ? edges[edges.length - 1].cursor : null
        }
      };
    }
  }
};

```

### 🔐 Why is the cursor base64-encoded?

The cursor is meant to be **opaque** — clients should treat it as a meaningless
string and never parse it. Base64 makes it *look* unparseable, so frontend
developers don't accidentally write code like `if (cursor.startsWith("id:"))`.
That matters because if any client depends on the cursor format, you can never
change it without breaking them. Base64 is the convention; the encoding itself
provides zero security.

### 🗄️ The Database SQL

If you are sorting by a unique `id`, the database jumps instantly to that row using its index. It is blazing fast:

```sql
SELECT * FROM users WHERE id > 20 ORDER BY id ASC LIMIT 10;

```

*(Note: If you sort by a non-unique column like 'Name', the backend must pack both the name and the ID into the cursor, and use tuple comparison: `WHERE (name, id) > ('John', 20)`).*

---

## 🤔 The "Why": Understanding Relay's Complex Design

If you look at the Relay schema above, it feels incredibly bloated. Why didn't Facebook just return a simple list of users with a cursor inside them? Here is why:

### 1. Why do we use `Edges` and `Nodes` instead of a simple list?

**Answer: To hold Relationship Metadata.**
A `Node` is pure data (User: Alice). It never changes.
But what if you query `projects.members`? You might want to know Alice's `role` (Admin) and `joinedAt` date. That data doesn't belong to Alice; it belongs to her *connection* to the project.

The `Edge` is the perfect place to put that data without polluting the pure User node.

* **Edge:** `{ cursor: "...", role: "Admin", joinedAt: "2023", node: { name: "Alice" } }`

### 2. Why does EVERY row need its own Cursor? (Why not just one `endCursor`?)

**Answer: Real-Time Cache Updates and Bi-Directional Scrolling.**
If you are just making a simple "Load More" button, you only really use the `endCursor` in `PageInfo`.

But imagine you are building a real-time feed like Twitter. A user clicks "Reply" to post #5. Your frontend UI needs to instantly insert that new reply into its local memory (cache) without refreshing the page.
Because post #5 has its *own* cursor, your frontend GraphQL client (like Apollo) knows *exactly* where to stitch that new data into the list. Furthermore, if you are building a Chat App and need to scroll UP to see older messages, having cursors on every edge lets you paginate backwards (`before: "cursor_of_first_item"`).

---

## 🧭 Which One Should I Use?

There is no universally "best" pagination — pick the one whose trade-offs match
your UI.

| Situation | Use this | Why |
| --- | --- | --- |
| Small list (< a few thousand rows), simple admin UI | **Offset** | Easiest to write; performance doesn't matter at this scale. |
| E-commerce / admin table with "Page 1, 2, 3 … 42" navigation | **Page-based** | Users expect numbered pages; you need `totalCount` for the page count anyway. |
| Infinite scroll feed (Twitter, Instagram, search results) | **Cursor (Relay)** | Stable under inserts (no data drift), fast even at page 10,000. |
| Real-time chat / message thread (scroll up to load older) | **Cursor (Relay)** | Bi-directional (`before` / `after`) and the per-row cursors make cache-stitching trivial. |
| Public GraphQL API (third-party developers will consume it) | **Cursor (Relay)** | It's the industry convention; client libraries (Apollo, Relay, urql) all expect this shape. |

### Quick mental model

* **Offset/Page** = *"give me items 21–30"* — easy to write, breaks under concurrent inserts, slow at deep pages.
* **Cursor** = *"give me 10 items after this bookmark"* — more code, more types, but stable and fast at any depth.

### A note on performance

`OFFSET` is not just "a little slower" at scale — it is genuinely catastrophic.
`OFFSET 1000000 LIMIT 10` forces PostgreSQL to read and discard a million rows
before it returns ten. Cursor pagination on an indexed column does **one index
lookup** regardless of how deep the user has scrolled. That's the real reason
cursors won — not aesthetics.
