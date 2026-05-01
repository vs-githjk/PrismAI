-- Add unique constraint on (meeting_id, user_id) so the chats table
-- can use upsert instead of a racy select+insert/update pattern.
-- Safe to run even if duplicate rows already exist (deduplicate first).

-- Remove any duplicate rows, keeping the most recently inserted one (highest id)
DELETE FROM chats
WHERE id NOT IN (
    SELECT MAX(id)
    FROM chats
    GROUP BY meeting_id, user_id
);

-- Add the unique constraint
ALTER TABLE chats
    ADD CONSTRAINT chats_meeting_id_user_id_key UNIQUE (meeting_id, user_id);
