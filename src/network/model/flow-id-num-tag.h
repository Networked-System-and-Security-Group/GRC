#include "ns3/tag.h"

namespace ns3 {
	/**
	* \ingroup tlt
	* \brief The packet header for a TLT packet
	*/
	class FlowIDNUMTag : public Tag
	{
	public:
		FlowIDNUMTag();
		static TypeId GetTypeId(void);
		virtual TypeId GetInstanceTypeId(void) const;
		virtual void Print(std::ostream &os) const;
		virtual uint32_t GetSerializedSize(void) const;
		virtual void Serialize(TagBuffer i) const;
		virtual void Deserialize(TagBuffer i);
		void SetId(int32_t ttl);
		int32_t GetId();
		uint32_t Getflowid();
		uint32_t GetFlowSize();
		void SetFlowSize(uint32_t fs);
		void SetAckReq(uint8_t ack);  // Setter for ack_req
		uint8_t GetAckReq() const;    // Getter for ack_req
		
	private:
		int32_t flow_stat;
		uint32_t flow_size;
		uint8_t ack_req;             // New member for acknowledgment request
		static uint16_t global_FLOWID_counter;
	};
} // namespace ns3
