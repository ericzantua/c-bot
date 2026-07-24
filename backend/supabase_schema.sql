-- C-Bot Supabase schema: products + knowledge + settings, with pgvector search.
-- Run once in the Supabase SQL editor (Dashboard → SQL → New query → Run).
-- Embedding dimension 1024 = Voyage voyage-3.5-lite default. Change everywhere
-- if you switch embedding model/size.

create extension if not exists vector;

-- ---------- Products ----------
create table if not exists products (
    item_code  text primary key,
    data       jsonb not null,          -- full ProductData record (edit without re-scrape)
    updated_at timestamptz default now()
);

create table if not exists product_chunks (
    id        bigint generated always as identity primary key,
    item_code text not null references products(item_code) on delete cascade,
    content   text not null,
    embedding vector(1024)
);
create index if not exists product_chunks_embedding_idx
    on product_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists product_chunks_item_idx on product_chunks(item_code);

-- ---------- Knowledge (policies / reference docs) ----------
create table if not exists knowledge_docs (
    doc_id     text primary key,
    title      text,
    source     text,
    chunks     int default 0,
    created_at timestamptz default now()
);

create table if not exists knowledge_chunks (
    id        bigint generated always as identity primary key,
    doc_id    text not null references knowledge_docs(doc_id) on delete cascade,
    title     text,
    content   text not null,
    embedding vector(1024)
);
create index if not exists knowledge_chunks_embedding_idx
    on knowledge_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists knowledge_chunks_doc_idx on knowledge_chunks(doc_id);

-- ---------- Settings (single row) ----------
create table if not exists settings (
    id                int primary key default 1,
    answer_guidelines text,
    constraint settings_singleton check (id = 1)
);
insert into settings (id, answer_guidelines) values (1, null)
    on conflict (id) do nothing;

-- ---------- Vector search functions (cosine similarity) ----------
create or replace function match_products(query_embedding vector(1024), match_count int)
returns table (item_code text, content text, data jsonb, similarity float)
language sql stable as $$
    select pc.item_code, pc.content, p.data,
           1 - (pc.embedding <=> query_embedding) as similarity
    from product_chunks pc
    join products p on p.item_code = pc.item_code
    order by pc.embedding <=> query_embedding
    limit match_count;
$$;

create or replace function match_knowledge(query_embedding vector(1024), match_count int)
returns table (content text, title text, similarity float)
language sql stable as $$
    select kc.content, kc.title,
           1 - (kc.embedding <=> query_embedding) as similarity
    from knowledge_chunks kc
    order by kc.embedding <=> query_embedding
    limit match_count;
$$;

-- ---------- Lock down: only the service-role key (backend) may touch data ----------
-- RLS on with NO policies = anon/public clients are denied; the backend uses the
-- service-role key which bypasses RLS. Keeps the data private.
alter table products         enable row level security;
alter table product_chunks   enable row level security;
alter table knowledge_docs   enable row level security;
alter table knowledge_chunks enable row level security;
alter table settings         enable row level security;
