"""Add indexes for user authentication performance

Revision ID: add_user_auth_indexes
Revises: 7d18f87ad727
Create Date: 2026-02-04

Note: the file name says 9e0f67b0f993, but the revision id Alembic has always
used for this migration is 'add_user_auth_indexes'. It is kept so databases
that already applied it stay consistent.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_user_auth_indexes'
down_revision: Union[str, Sequence[str], None] = '7d18f87ad727'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Create indexes for better query performance
    op.create_index('idx_user_email', 'users', ['email'], unique=False)
    op.create_index('idx_user_username', 'users', ['username'], unique=False)
    op.create_index('idx_user_reset_token', 'users', ['reset_password_token'], unique=False)

    # Optional: Composite index for the OR query in authenticate_user
    op.create_index('idx_user_email_username_active', 'users', ['email', 'username', 'is_active'], unique=False)


def downgrade():
    # Remove indexes if rolling back
    op.drop_index('idx_user_email_username_active', table_name='users')
    op.drop_index('idx_user_reset_token', table_name='users')
    op.drop_index('idx_user_username', table_name='users')
    op.drop_index('idx_user_email', table_name='users')
