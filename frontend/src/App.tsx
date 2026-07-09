import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import BrandHealth from './pages/BrandHealth';
import AspectDrilldown from './pages/AspectDrilldown';
import ReviewQueue from './pages/ReviewQueue';
import AlertFeed from './pages/AlertFeed';
import PostExplorer from './pages/PostExplorer';
import Pipeline from './pages/Pipeline';
import PostLifecycle from './pages/PostLifecycle';
import CompetitorInsights from './pages/CompetitorInsights';
import Notifications from './pages/Notifications';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<BrandHealth />} />
        <Route path="/aspects/:aspect" element={<AspectDrilldown />} />
        <Route path="/lifecycle" element={<PostLifecycle />} />
        <Route path="/insights" element={<CompetitorInsights />} />
        <Route path="/review" element={<ReviewQueue />} />
        <Route path="/alerts" element={<AlertFeed />} />
        <Route path="/posts" element={<PostExplorer />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/notifications" element={<Notifications />} />
      </Route>
    </Routes>
  );
}
