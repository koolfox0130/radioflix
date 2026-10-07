import SchedulePage from "../../schedule/page";
import InterceptedRoute from "../../components/InterceptedRoute";

export default function InterceptedSchedulePage() {
  return <InterceptedRoute skipWhenSegment="schedule"><SchedulePage /></InterceptedRoute>;
}
