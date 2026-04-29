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
import VirtualAssistant from "@/components/VirtualAssistant";

import RouteTracker from "@/components/RouteTracker";

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
          <Route path="/documentation" element={<ApiDocs />} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />

          {/* Client portal */}
          <Route path="/portal" element={<Protected><PortalLayout admin={false} /></Protected>}>
            <Route index element={<ClientDashboard />} />
            <Route path="appointments" element={<ClientAppointments />} />
            <Route path="documents" element={<ClientDocuments />} />
            <Route path="interventions" element={<ClientInterventions />} />
            <Route path="users" element={<ClientUsersTracking />} />
            <Route path="notes/:kind" element={<UserNotesPage />} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<Protected admin><PortalLayout admin /></Protected>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
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
