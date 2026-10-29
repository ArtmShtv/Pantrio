"""opaque refresh tokens with families

Switches refresh tokens from JWTs keyed by jti to random strings stored as
a SHA-256 hash, grouped into families (one family = one device session).

Existing rows are deleted first: old tokens can't be converted (we never
stored their raw value), and the new NOT NULL columns would have nothing to
hold. Effect: everyone currently logged in has to log in again.

Revision ID: cff131a2cbe0
Revises: 4e175514a852
Create Date: 2026-10-29 18:16:41.758478

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cff131a2cbe0'
down_revision: Union[str, Sequence[str], None] = '4e175514a852'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM refresh_tokens")
    op.add_column('refresh_tokens', sa.Column('family_id', sa.Uuid(), nullable=False))
    op.add_column('refresh_tokens', sa.Column('token_hash', sa.String(length=64), nullable=False))
    op.add_column('refresh_tokens', sa.Column('used_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f('uq_refresh_tokens_jti'), 'refresh_tokens', type_='unique')
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_unique_constraint(op.f('uq_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'])
    op.drop_column('refresh_tokens', 'jti')
    op.drop_column('refresh_tokens', 'replaced_by_jti')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM refresh_tokens")
    op.add_column('refresh_tokens', sa.Column('replaced_by_jti', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('refresh_tokens', sa.Column('jti', sa.UUID(), autoincrement=False, nullable=False))
    op.drop_constraint(op.f('uq_refresh_tokens_token_hash'), 'refresh_tokens', type_='unique')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.create_unique_constraint(op.f('uq_refresh_tokens_jti'), 'refresh_tokens', ['jti'], postgresql_nulls_not_distinct=False)
    op.drop_column('refresh_tokens', 'used_at')
    op.drop_column('refresh_tokens', 'token_hash')
    op.drop_column('refresh_tokens', 'family_id')
