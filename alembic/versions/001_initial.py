"""Initial migration - create all tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    channel_type = postgresql.ENUM(
        'telegram', 'vk', 'whatsapp', 'max',
        name='channeltype'
    )
    channel_type.create(op.get_bind())

    message_status = postgresql.ENUM(
        'pending', 'sent', 'delivered', 'read', 'failed',
        name='messagestatus'
    )
    message_status.create(op.get_bind())

    member_role = postgresql.ENUM(
        'owner', 'admin', 'agent', 'viewer',
        name='memberrole'
    )
    member_role.create(op.get_bind())

    # Create workspaces table
    op.create_table('workspaces',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.BigInteger(), nullable=True),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workspaces_owner_id', 'workspaces', ['owner_id'])

    # Create users table
    op.create_table('users',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_workspace_id', 'users', ['workspace_id'])

    # Create members table
    op.create_table('members',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('role', member_role, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'workspace_id', name='uq_members_user_workspace')
    )
    op.create_index('ix_members_workspace_id', 'members', ['workspace_id'])
    op.create_index('ix_members_user_id', 'members', ['user_id'])

    # Create channel_accounts table
    op.create_table('channel_accounts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_type', channel_type, nullable=False),
        sa.Column('external_account_id', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('credentials', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('webhook_secret', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('rate_limit_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_channel_accounts_workspace_id', 'channel_accounts', ['workspace_id'])
    op.create_index('ix_channel_accounts_channel_type', 'channel_accounts', ['channel_type'])
    op.create_index(
        'ix_channel_accounts_unique',
        'channel_accounts',
        ['workspace_id', 'channel_type', 'external_account_id'],
        unique=True
    )

    # Create conversations table
    op.create_table('conversations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_account_id', sa.BigInteger(), nullable=False),
        sa.Column('external_chat_id', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('participants', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('last_message_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_conversations_workspace_id', 'conversations', ['workspace_id'])
    op.create_index('ix_conversations_channel_account_id', 'conversations', ['channel_account_id'])
    op.create_index(
        'ix_conversations_unique',
        'conversations',
        ['channel_account_id', 'external_chat_id'],
        unique=True
    )

    # Create messages table with sequence_id for strict ordering
    op.create_table('messages',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('conversation_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_account_id', sa.BigInteger(), nullable=False),
        sa.Column('external_message_id', sa.String(length=255), nullable=True),
        sa.Column('sequence_id', sa.BigInteger(), nullable=False),
        sa.Column('sender_id', sa.BigInteger(), nullable=True),
        sa.Column('sender_type', sa.String(length=50), nullable=False),  # 'user', 'contact', 'system'
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('message_type', sa.String(length=50), nullable=False, server_default='text'),  # text, image, video, etc
        sa.Column('media_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'),
        sa.Column('status', message_status, nullable=False, server_default='pending'),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('server_received_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('external_sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_messages_workspace_id', 'messages', ['workspace_id'])
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_messages_sequence_id', 'messages', ['conversation_id', 'sequence_id'])
    op.create_index(
        'ix_messages_external_unique',
        'messages',
        ['channel_account_id', 'external_message_id'],
        unique=True,
        postgresql_where=sa.text('external_message_id IS NOT NULL')
    )
    op.create_index('ix_messages_server_received_at', 'messages', ['server_received_at'])
    op.create_index('ix_messages_status', 'messages', ['status'])
    # GIN index for metadata search
    op.create_index('ix_messages_metadata_gin', 'messages', ['metadata'], postgresql_using='gin')

    # Create audit_logs table
    op.create_table('audit_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('resource_type', sa.String(length=100), nullable=True),
        sa.Column('resource_id', sa.BigInteger(), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_workspace_id', 'audit_logs', ['workspace_id'])
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # Add foreign key constraints
    op.create_foreign_key('fk_users_workspace', 'users', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_members_user', 'members', 'users', ['user_id'], ['id'])
    op.create_foreign_key('fk_members_workspace', 'members', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_channel_accounts_workspace', 'channel_accounts', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_conversations_workspace', 'conversations', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_conversations_channel_account', 'conversations', 'channel_accounts', ['channel_account_id'], ['id'])
    op.create_foreign_key('fk_messages_workspace', 'messages', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_messages_conversation', 'messages', 'conversations', ['conversation_id'], ['id'])
    op.create_foreign_key('fk_messages_channel_account', 'messages', 'channel_accounts', ['channel_account_id'], ['id'])
    op.create_foreign_key('fk_audit_logs_workspace', 'audit_logs', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('fk_audit_logs_user', 'audit_logs', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    # Drop tables in reverse order (foreign keys first)
    op.drop_table('audit_logs')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('channel_accounts')
    op.drop_table('members')
    op.drop_table('users')
    op.drop_table('workspaces')

    # Drop enum types
    op.execute('DROP TYPE IF EXISTS memberrole')
    op.execute('DROP TYPE IF EXISTS messagestatus')
    op.execute('DROP TYPE IF EXISTS channeltype')
