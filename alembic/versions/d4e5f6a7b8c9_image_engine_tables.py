"""add image_jobs and image_outputs tables for local image engine

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'image_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('comfy_prompt_id', sa.String(length=100), nullable=True),
        sa.Column('input_params', sa.JSON(), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=True),
        sa.Column('total_steps', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_image_jobs_created_at', 'image_jobs', ['created_at'], unique=False)
    op.create_index('ix_image_jobs_project_id', 'image_jobs', ['project_id'], unique=False)
    op.create_index('ix_image_jobs_status', 'image_jobs', ['status'], unique=False)
    op.create_index('ix_image_jobs_user_id', 'image_jobs', ['user_id'], unique=False)

    op.create_table(
        'image_outputs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('thumbnail_path', sa.Text(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=True),
        sa.Column('output_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['image_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_image_outputs_job_id', 'image_outputs', ['job_id'], unique=False)


def downgrade():
    op.drop_index('ix_image_outputs_job_id', table_name='image_outputs')
    op.drop_table('image_outputs')
    op.drop_index('ix_image_jobs_user_id', table_name='image_jobs')
    op.drop_index('ix_image_jobs_status', table_name='image_jobs')
    op.drop_index('ix_image_jobs_project_id', table_name='image_jobs')
    op.drop_index('ix_image_jobs_created_at', table_name='image_jobs')
    op.drop_table('image_jobs')
