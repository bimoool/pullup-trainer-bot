-- Генератор запросов «хэш строк по колонкам, существовавшим ДО миграции». Выполнять на состоянии ДО (после остановки писателей):
--   psql -At -f gen_hash_queries.sql > hash_queries.sql
-- Затем ТОТ ЖЕ hash_queries.sql выполнить ДО и ПОСЛЕ миграции и сравнить вывод (diff). Добавленные миграциями колонки/таблицы
-- в хэш не входят, поэтому различие означает изменение СУЩЕСТВОВАВШИХ данных. Таблицы без колонки id в проверку не входят
-- (они перечислены в конце списком — смотреть отдельно).
select 'select ' || quote_literal(t.table_name) || ' as tbl, count(*) as n, md5(coalesce(string_agg(row('
       || string_agg(quote_ident(c.column_name), ',' order by c.ordinal_position)
       || ')::text, ''|'' order by id), '''')) as h from ' || quote_ident(t.table_name) || ';'
from information_schema.tables t
join information_schema.columns c on c.table_schema = t.table_schema and c.table_name = t.table_name
where t.table_schema = 'public' and t.table_type = 'BASE TABLE' and t.table_name <> 'alembic_version'
  and exists (select 1 from information_schema.columns k
              where k.table_schema = 'public' and k.table_name = t.table_name and k.column_name = 'id')
group by t.table_name
order by t.table_name;
