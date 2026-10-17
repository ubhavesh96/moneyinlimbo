from django.urls import path, re_path

from cases import views

urlpatterns = [
    path("", views.home, name="index"),
    path("role", views.switch_role, name="switch-role"),
    path("officer/queue", views.officer_queue, name="officer-queue"),
    path("officer/drafts", views.officer_drafts, name="officer-drafts"),
    path("officer/new", views.officer_new, name="officer-new"),
    path("officer/insights", views.officer_insights, name="officer-insights"),
    path("officer/cases/<str:case_id>", views.officer_case, name="officer-case"),
    path("auditor/explorer", views.auditor_explorer, name="auditor-explorer"),
    path("auditor/replay/<str:case_id>", views.auditor_replay, name="auditor-replay"),
    path("auditor/decisions", views.auditor_decisions, name="auditor-decisions"),
    path("auditor/rules", views.auditor_rules, name="auditor-rules"),
    path("auditor/models", views.auditor_models, name="auditor-models"),
    path("auditor/exports", views.auditor_exports, name="auditor-exports"),
    re_path(r"^api/(?P<path>.*)$", views.agent_api, name="agent-api"),
]
