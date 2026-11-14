"""Устройство базы: таблицы, индексы, триггеры, что сравнивает самопроверка."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.


EXCLUDED_DDL = ('create table if not exists excluded(disk text not null, path text not null, size integer, sha text, '
                'name_lc text, origin text, primary key(disk, path)) without rowid')

SCHEMA = [
    'create table if not exists files(disk text not null, path text not null, size integer, sha text, origin text, '
    'name_lc text, mtime integer, ev text, sha_exp text, primary key(disk, path)) without rowid',
    'create table if not exists meta(key text primary key, value text)',
    'create table if not exists disks(disk text primary key, label text, hashed integer, total integer, status text, scanned real)',
    'create table if not exists issues(disk text, path text, kind text, note text)',
    'create table if not exists applied(module text primary key, kind text, time real, size integer, mtime_ns integer, '
    'checksum text, rows integer, applied_at text, changed integer)',
    'create table if not exists scan_folders(disk text not null, folder text not null, time real, primary key(disk, folder))',
    EXCLUDED_DDL,
]
INDEXES = [
    'create index if not exists files_sha on files(sha, disk) where sha is not null',
    'create index if not exists files_exp on files(sha_exp, disk) where sha_exp is not null',
    'create index if not exists files_name on files(name_lc, size, disk)',
    'create index if not exists issues_disk on issues(disk)',
]
DIGEST_TABLES = {          # что сравнивается при самопроверке rebuild (служебные applied и meta - нет)
    'files': 'disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp',
    'disks': 'disk, label, hashed, total, status, scanned',
    'issues': 'disk, path, kind, note',
    'excluded': 'disk, path, size, sha, name_lc, origin',
    'scan_folders': 'disk, folder, time',
}
DERIVED_SCHEMA = [
    'create table if not exists presence(sha text primary key, e45 text, e77 text, ndisks integer, ncopies integer) without rowid',
    'create table if not exists folders(disk text not null, folder text not null, depth integer, folder_lc text, '
    'files integer, bytes integer, ' + ', '.join(f'n{i} integer, b{i} integer' for i in range(5)) +
    ', primary key(disk, folder)) without rowid',
]
TRIGGERS = [
    'create temp table if not exists touched(sha text primary key) without rowid',
    'create temp table if not exists delta(disk text, path text, size integer, name_lc text, sign integer)',
    '''create temp trigger if not exists t_files_ins after insert on files begin
         insert or ignore into touched select new.sha where new.sha is not null;
         insert or ignore into touched select new.sha_exp where new.sha_exp is not null;
         insert into delta values (new.disk, new.path, new.size, new.name_lc, 1); end''',
    '''create temp trigger if not exists t_files_del after delete on files begin
         insert or ignore into touched select old.sha where old.sha is not null;
         insert or ignore into touched select old.sha_exp where old.sha_exp is not null;
         insert into delta values (old.disk, old.path, old.size, old.name_lc, -1); end''',
    '''create temp trigger if not exists t_files_upd after update on files begin
         insert or ignore into touched select old.sha where old.sha is not null;
         insert or ignore into touched select old.sha_exp where old.sha_exp is not null;
         insert or ignore into touched select new.sha where new.sha is not null;
         insert or ignore into touched select new.sha_exp where new.sha_exp is not null;
         insert into delta values (old.disk, old.path, old.size, old.name_lc, -1);
         insert into delta values (new.disk, new.path, new.size, new.name_lc, 1); end''',
]
DIGEST_TABLES.update({
    'presence': 'sha, e45, e77, ndisks, ncopies',
    'folders': 'disk, folder, depth, folder_lc, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5)),
})
