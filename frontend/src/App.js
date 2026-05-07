import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import MarketingLayout from "@/components/MarketingLayout";
import PortalLayout from "@/components/PortalLayout";

// Public
import Home from "@/pages/public/Home";
import Missions from "@/pages/public/Missions";
import Specialisations from "@/pages/public/Specialisations";
import Catalogue from "@/pages/public/Catalogue";
import Contact from "@/pages/public/Contact";
import RDV from "@/pages/public/RDV";
import Testimonials from "@/pages/public/Testimonials";
import Feedback from "@/pages/public/Feedback";
import CaseStudies from "@/pages/public/CaseStudies";
import CaseStudyDetail from "@/pages/public/CaseStudyDetail";
import Blog from "@/pages/public/Blog";
import BlogPost from "@/pages/public/BlogPost";
import StatusPage from "@/pages/public/Status";

// Auth
import Login from "@/pages/auth/Login";

// Portal
import ClientDashboard from "@/pages/portal/Dashboard";
import ClientAppointments from "@/pages/portal/Appointments";
import ClientDocuments from "@/pages/portal/Documents";
import ClientInterventions from "@/pages/portal/Interventions";
import ClientUsersTracking from "@/pages/portal/UsersTracking";
import UserNotesPage from "@/pages/portal/UserNotes";

// Admin
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminClients from "@/pages/admin/AdminClients";
import AdminAppointments from "@/pages/admin/AdminAppointments";
import AdminInterventions from "@/pages/admin/AdminInterventions";
import AdminDocuments from "@/pages/admin/AdminDocuments";
import AdminContents from "@/pages/admin/AdminContents";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminContacts from "@/pages/admin/AdminContacts";
import AdminTrackedUsers from "@/pages/admin/AdminTrackedUsers";
import AdminTestimonials from "@/pages/admin/AdminTestimonials";
import AdminCaseStudies from "@/pages/admin/AdminCaseStudies";
import AdminBlog from "@/pages/admin/AdminBlog";
import AdminNewsletter from "@/pages/admin/AdminNewsletter";
import AdminVisits from "@/pages/admin/AdminVisits";
import AdminDeployments from "@/pages/admin/AdminDeployments";
import AdminBlacklist from "@/pages/admin/AdminBlacklist";
import AdminAccessLogs from "@/pages/admin/AdminAccessLogs";
import AdminApiTraces from "@/pages/admin/AdminApiTraces";
import AdminHealthDashboard from "@/pages/admin/AdminHealthDashboard";
import AdminDbExplorer from "@/pages/admin/AdminDbExplorer";
import AdminFormations from "@/pages/admin/AdminFormations";
import AdminIntegrationLinks from "@/pages/admin/AdminIntegrationLinks";
import AdminMessaging from "@/pages/admin/AdminMessaging";
import AdminAutomations from "@/pages/admin/AdminAutomations";
import AdminWaTemplates from "@/pages/admin/AdminWaTemplates";
import AdminClientTimeline from "@/pages/admin/AdminClientTimeline";
import AdminClientFeatures from "@/pages/admin/AdminClientFeatures";
import AdminUsage from "@/pages/admin/AdminUsage";
import AdminPolicies from "@/pages/admin/AdminPolicies";
import Launch from "@/pages/public/Launch";
import FormsList from "@/pages/portal/FormsList";
import FormEditor from "@/pages/portal/FormEditor";
import FormRunner from "@/pages/portal/FormRunner";
import FormsAnalytics from "@/pages/portal/FormsAnalytics";
import FormAnalyticsDetail from "@/pages/portal/FormAnalyticsDetail";
import Contacts from "@/pages/portal/Contacts";
import MediaGenerator from "@/pages/portal/MediaGenerator";
import MediaLibrary from "@/pages/portal/MediaLibrary";
import MyPayments from "@/pages/portal/MyPayments";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import SmsBulk from "@/pages/portal/SmsBulk";
import PayLink from "@/pages/public/PayLink";
import PublicForm from "@/pages/public/PublicForm";
import PoliciesPage from "@/pages/public/Policies";
import { FormationsList, FormationDetail } from "@/pages/portal/Formations";
import VirtualAssistant from "@/components/VirtualAssistant";

import RouteTracker from "@/components/RouteTracker";
import WebhookResultModal from "@/components/WebhookResultModal";

import ApiDocs from "@/pages/ApiDocs";

const PublicRoute = ({ children }) => <MarketingLayout>{children}</MarketingLayout>;

const Protected = ({ admin = false, children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "admin") return <Navigate to="/portal" replace />;
  return children;
};

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster richColors position="top-right" />
        <WebhookResultModal />
        <RouteTracker />
        <Routes>
          {/* Public marketing */}
          <Route path="/" element={<PublicRoute><Home /></PublicRoute>} />
          <Route path="/missions" element={<PublicRoute><Missions /></PublicRoute>} />
          <Route path="/specialisations" element={<PublicRoute><Specialisations /></PublicRoute>} />
          <Route path="/catalogue" element={<PublicRoute><Catalogue /></PublicRoute>} />
          <Route path="/contact" element={<PublicRoute><Contact /></PublicRoute>} />
          <Route path="/rdv" element={<PublicRoute><RDV /></PublicRoute>} />
          <Route path="/temoignages" element={<PublicRoute><Testimonials /></PublicRoute>} />
          <Route path="/etudes-de-cas" element={<PublicRoute><CaseStudies /></PublicRoute>} />
          <Route path="/etudes-de-cas/:slug" element={<PublicRoute><CaseStudyDetail /></PublicRoute>} />
          <Route path="/blog" element={<PublicRoute><Blog /></PublicRoute>} />
          <Route path="/blog/:slug" element={<PublicRoute><BlogPost /></PublicRoute>} />
          <Route path="/feedback/:token" element={<Feedback />} />
          <Route path="/uptime" element={<StatusPage />} />
          <Route path="/launch" element={<Launch />} />
          <Route path="/f/:fid" element={<PublicForm />} />
          <Route path="/pay/:slug" element={<PayLink />} />
          <Route path="/documentation" element={<ApiDocs />} />
          <Route path="/politiques" element={<PublicRoute><PoliciesPage /></PublicRoute>} />
          <Route path="/politiques/:slug" element={<PublicRoute><PoliciesPage /></PublicRoute>} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />

          {/* Client portal */}
          <Route path="/portal" element={<Protected><PortalLayout admin={false} /></Protected>}>
            <Route index element={<ClientDashboard />} />
            <Route path="appointments" element={<ClientAppointments />} />
            <Route path="documents" element={<ClientDocuments />} />
            <Route path="interventions" element={<ClientInterventions />} />
            <Route path="users" element={<ClientUsersTracking />} />
            <Route path="formations" element={<FormationsList />} />
            <Route path="formations/:fid" element={<FormationDetail />} />
            <Route path="forms" element={<FormsList />} />
            <Route path="forms/analytics" element={<FormsAnalytics />} />
            <Route path="forms/:fid/edit" element={<FormEditor />} />
            <Route path="forms/:fid/fill" element={<FormRunner />} />
            <Route path="forms/:fid/analytics" element={<FormAnalyticsDetail />} />
            <Route path="contacts" element={<Contacts />} />
            <Route path="media-library" element={<MediaLibrary />} />
            <Route path="media-generator" element={<MediaGenerator />} />
            <Route path="notes/:kind" element={<UserNotesPage />} />
            <Route path="payments" element={<ErrorBoundary name="MyPayments"><MyPayments /></ErrorBoundary>} />
            <Route path="sms" element={<ErrorBoundary name="SmsBulk"><SmsBulk /></ErrorBoundary>} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<Protected admin><PortalLayout admin /></Protected>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="clients/:id/timeline" element={<AdminClientTimeline />} />
            <Route path="clients/:id/features" element={<AdminClientFeatures />} />
            <Route path="usage" element={<AdminUsage />} />
            <Route path="appointments" element={<AdminAppointments />} />
            <Route path="interventions" element={<AdminInterventions />} />
            <Route path="documents" element={<AdminDocuments />} />
            <Route path="contents" element={<AdminContents />} />
            <Route path="contacts" element={<AdminContacts />} />
            <Route path="tracked-users" element={<AdminTrackedUsers />} />
            <Route path="testimonials" element={<AdminTestimonials />} />
            <Route path="case-studies" element={<AdminCaseStudies />} />
            <Route path="blog" element={<AdminBlog />} />
            <Route path="newsletter" element={<AdminNewsletter />} />
            <Route path="visits" element={<AdminVisits />} />
            <Route path="deployments" element={<AdminDeployments />} />
            <Route path="blacklist" element={<AdminBlacklist />} />
            <Route path="access-logs" element={<AdminAccessLogs />} />
            <Route path="api-traces" element={<AdminApiTraces />} />
            <Route path="health" element={<AdminHealthDashboard />} />
            <Route path="db-explorer" element={<AdminDbExplorer />} />
            <Route path="formations" element={<AdminFormations />} />
            <Route path="forms" element={<FormsList />} />
            <Route path="forms/analytics" element={<FormsAnalytics />} />
            <Route path="forms/:fid/edit" element={<FormEditor />} />
            <Route path="forms/:fid/fill" element={<FormRunner />} />
            <Route path="forms/:fid/analytics" element={<FormAnalyticsDetail />} />
            <Route path="messaging" element={<AdminMessaging />} />
            <Route path="automations" element={<AdminAutomations />} />
            <Route path="whatsapp-templates" element={<AdminWaTemplates />} />
            <Route path="policies" element={<AdminPolicies />} />
            <Route path="integration-links" element={<AdminIntegrationLinks />} />
            <Route path="notes/:kind" element={<UserNotesPage />} />
            <Route path="settings" element={<AdminSettings />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <VirtualAssistant />
      </BrowserRouter>
    </AuthProvider>
  );
}
