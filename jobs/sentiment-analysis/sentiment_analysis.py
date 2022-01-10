"""Generate account statements.

This module will create statement records for each account.
"""

import os

import psycopg2
from api.services.sentiment_analysis import overall_sentiment
from flask import Flask

import config
from utils.logger import setup_logging

setup_logging(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logging.conf'))  # important to do this first
APP_CONFIG = config.get_named_config(os.getenv('DEPLOYMENT_ENV', 'production'))


# pylint:disable=no-member

def create_app(run_mode=os.getenv('FLASK_ENV', 'production')):
    """Return a configured Flask App using the Factory method."""
    app = Flask(__name__)
    app.config.from_object(config.CONFIGURATION[run_mode])
    app.logger.info('<<<< Starting Sentiment analysis job >>>>')
    register_shellcontext(app)
    return app


def register_shellcontext(app):
    """Register shell context objects."""

    def shell_context():
        """Shell context objects."""
        return {
            'app': app
        }  # pragma: no cover

    app.shell_context_processor(shell_context)


def update_sentiment():
    """Update sentiment by querying the records."""
    conn = None
    try:
        # connect to the PostgreSQL server
        conn = psycopg2.connect(**APP_CONFIG.DB_PG_CONFIG)

        table_name = APP_CONFIG.DATABASE_TABLE_NAME
        input_col = APP_CONFIG.DATABASE_INPUT_COLUMN
        output_col = APP_CONFIG.DATABASE_OUTPUT_COLUMN

        # Find primary key for the table.
        primary_keys = _find_primary_keys(conn, table_name)

        # Query the rows from table.
        cols_to_query = f'{primary_keys},{input_col}'
        rows_query = f"select {cols_to_query} from {table_name} where coalesce({output_col}, '') = ''"

        try:
            cur = conn.cursor()
            cur.execute(rows_query)
            colnames = [desc[0] for desc in cur.description]
            results = cur.fetchall()
        finally:
            cur.close()

        _perform_analysis(colnames, conn, results)

        # commit the changes
        conn.commit()

    except (Exception, psycopg2.DatabaseError) as error:  # noqa
        raise error
    finally:
        if conn is not None:
            conn.close()


def _find_primary_keys(conn, table_name):
    pk_query = f'SELECT column_name FROM information_schema.table_constraints ' \
               f'JOIN information_schema.key_column_usage ' \
               f'USING (constraint_catalog, constraint_schema, constraint_name, table_catalog, table_schema, ' \
               f"table_name) WHERE constraint_type = 'PRIMARY KEY'  " \
               f"AND (table_name) = ( '{table_name}') ORDER BY ordinal_position;"

    try:
        cur = conn.cursor()
        cur.execute(pk_query)
        primary_keys = ','.join(cur.fetchall()[0])
    finally:
        cur.close()

    return primary_keys


def _perform_analysis(colnames, conn, results):
    # Create a list of dicts with column name and results.
    table_name = APP_CONFIG.DATABASE_TABLE_NAME
    input_col = APP_CONFIG.DATABASE_INPUT_COLUMN
    output_col = APP_CONFIG.DATABASE_OUTPUT_COLUMN

    query_results = [dict(zip(colnames, result)) for result in results]
    count: int = 0
    for result_dict in query_results:
        sentiment = overall_sentiment(result_dict.get(input_col))
        update_qry = f"update {table_name} set {output_col}='{sentiment}' where 1=1 "
        for key, value in result_dict.items():
            if key != input_col:
                update_qry += f" AND {key}='{value}' "

        try:
            cur = conn.cursor()
            cur.execute(update_qry)
        finally:
            cur.close()

        count += 1
    print(f'Updated {count} records')


def run():
    """Run the job."""
    application = create_app()
    application.app_context().push()
    update_sentiment()


if __name__ == '__main__':
    run()