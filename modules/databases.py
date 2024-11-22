import aiosqlite

async def create_database(database_name: str):
    async with aiosqlite.connect(database_name) as database:
        await database.execute('''
            CREATE TABLE IF NOT EXISTS maps (
                name TEXT not null primary key,
                song TEXT,
                total_attempts integer NOT NULL,
                total_completions integer NOT NULL,
                best_attempt text NOT NULL,
                best_completion text NOT NULL
            )
        ''')

        await database.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                map text not null,
                session_start integer NOT NULL,
                session_end integer,
                total_attempts integer NOT NULL,
                total_completions integer NOT NULL,
                best_attempt text NOT NULL,
                best_completion text NOT NULL,
                FOREIGN KEY (map) REFERENCES maps (name)
                )
        ''')

        await database.commit()
