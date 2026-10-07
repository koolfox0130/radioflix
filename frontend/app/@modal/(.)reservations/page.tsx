import ReservationsPage from "../../reservations/page";
import InterceptedRoute from "../../components/InterceptedRoute";

export default function InterceptedReservationsPage() {
  return <InterceptedRoute skipWhenSegment="reservations"><ReservationsPage /></InterceptedRoute>;
}
